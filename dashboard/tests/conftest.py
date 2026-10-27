"""Fixtures of the qc-dashboard author tests (SPEC-013, SPEC-028, SPEC-018).

Only the HTTP boundary is mocked: ``httpx.MockTransport`` answers with bodies built from the
``qc_contracts`` models and records every request. No test touches the network. Keys are
generated at run time, so no credential appears as a literal (R-03).
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import streamlit as st

from qc_contracts import (
    DeviceStatus,
    InspectionRead,
    MetricsSummary,
    Page,
    Source,
    SpcExcludedLot,
    SpcPoint,
    SpcResponse,
    TimeseriesPoint,
)
from qc_dashboard import api

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
VIEWS_DIR = DASHBOARD_DIR / "views"
APP_FILE = DASHBOARD_DIR / "app.py"
BASE_URL = "https://api.test"
CONFIG_VARS = ("API_BASE_URL", "READ_API_KEY", "MODEL_METRICS_PATH")
SHA = "a" * 64


def new_key() -> str:
    return f"k-{secrets.token_hex(8)}"


def summary(**overrides: Any) -> MetricsSummary:
    values: dict[str, Any] = {
        "total": 40,
        "defective": 5,
        "defect_rate": 0.125,
        "unknown_count": 3,
        "needs_review_count": 4,
        "by_grade": {"perfect": 5, "good": 10},
        "by_object_type": {"screw": 20, "nut": 17, "unknown": 3},
        "mean_type_confidence": 0.9,
        "mean_grade_score": 1.8456,
    }
    values.update(overrides)
    return MetricsSummary.model_validate(values)


def inspection(**overrides: Any) -> InspectionRead:
    values: dict[str, Any] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-01",
        "lot_id": "L-001",
        "inspected_at": "2026-11-03T15:00:00Z",
        "object_type": "screw",
        "grade": "good",
        "grade_score": 1.25,
        "type_confidence": 0.875,
        "grade_confidence": 0.7,
        "needs_review": False,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "latency_ms": 42,
        "source": "live",
        "received_at": "2026-11-03T15:00:01Z",
        "is_defective": False,
    }
    values.update(overrides)
    return InspectionRead.model_validate(values)


def device_status(**overrides: Any) -> DeviceStatus:
    """A device with a recent heartbeat (``online``) and a ``live`` latest inspection."""
    values: dict[str, Any] = {
        "device_id": "edge-01",
        "last_seen_at": "2026-11-03T15:00:00Z",
        "last_heartbeat_at": "2026-11-03T15:00:00Z",
        "online": True,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "app_version": "0.0.0",
        "uptime_s": 7500,
        "outbox_pending": 2,
        "outbox_dead": 1,
        "last_source": "live",
    }
    values.update(overrides)
    return DeviceStatus.model_validate(values)


def spc_point(lot_id: str, *, out_of_control: bool = False, **overrides: Any) -> SpcPoint:
    start = datetime(2026, 11, 3, 15, tzinfo=UTC)
    values: dict[str, Any] = {
        "lot_id": lot_id,
        "started_at": start,
        "ended_at": start + timedelta(hours=1),
        "n": 25,
        "defects": 4,
        "p": 0.16,
        "cl": 0.18,
        "ucl": 0.41,
        "lcl": 0.0,
        "out_of_control": out_of_control,
    }
    values.update(overrides)
    return SpcPoint.model_validate(values)


def spc_response(**overrides: Any) -> SpcResponse:
    values: dict[str, Any] = {
        "baseline_lots": 20,
        "min_lot_size": 5,
        "source": "live",
        "p_bar": 0.18,
        "points": [
            spc_point("L-001"),
            spc_point("L-002"),
            spc_point("L-003", out_of_control=True, defects=12, p=0.48),
            spc_point("L-004"),
        ],
        "excluded_lots": [SpcExcludedLot(lot_id="L-009", n=3)],
        "message": None,
        "max_points": 100,
        "valid_lots_total": 4,
        "excluded_lots_total": 1,
    }
    values.update(overrides)
    return SpcResponse.model_validate(values)


def metrics_document(**overrides: Any) -> dict[str, Any]:
    """A ``metrics.json`` with every top-level key of SPEC-012 section 4.7."""
    grades = ("perfect", "good", "fair", "poor", "unusable")
    document: dict[str, Any] = {
        "model_version": "partqc-test-v0",
        "model_sha256": "0123456789abcdef" * 4,
        "evaluated_at": "2026-11-20T13:30:00+00:00",
        "split_file": "ml/splits/split_v1.csv",
        "split_sha256": SHA,
        "manifest_sha256": SHA,
        "labels": {"object_types": ["screw", "nut", "other"], "grades": list(grades)},
        "decision": {
            "type_threshold": 0.7,
            "unusable_threshold": 0.5,
            "grade_review_threshold": 0.6,
        },
        "type_accuracy": 0.96,
        "type_confusion": [[10, 0, 0], [0, 10, 0], [0, 0, 10]],
        "grade_qwk": 0.70,
        "grade_mae": 0.31,
        "grade_off_by_one_accuracy": 0.93,
        "grade_confusion": [[2, 0, 0, 0, 0] for _ in grades],
        "grade_per_class": {
            g: {"precision": 0.8, "recall": 0.75, "f1": 0.77, "support": 8} for g in grades
        },
        "unusable_recall": 0.9,
        "unusable_precision": 0.85,
        "defective_recall": 0.88,
        "defective_precision": 0.9,
        "unknown_rate_on_other": 0.95,
        "false_unknown_rate": 0.02,
        "needs_review_rate": 0.1,
        "latency_ms_p50": 40.5,
        "latency_ms_p95": 120.0,
        "latency_machine": "notebook-borda",
        "latency_runs": 100,
        "counts": {},
        "grade_qwk_ci95": [0.6, 0.78],
        "unusable_recall_ci95": [0.8, 0.97],
        "defective_recall_ci95": None,
        "n_items_test_by_grade": {g: 4 for g in grades},
        "warnings": [],
    }
    document.update(overrides)
    return document


class MockApi:
    """Routes ``/api/v1/*`` to configurable bodies and records the requests."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.summary_live = summary()
        self.summary_simulated = summary(total=0)
        self.timeseries = [
            TimeseriesPoint(
                bucket_start=datetime(2026, 11, 3, 15, tzinfo=UTC),
                total=10,
                defective=2,
                defect_rate=0.2,
            )
        ]
        self.spc = spc_response()
        # Origin of the SPC response; ``None`` echoes the ``source`` of the query, as the API does.
        self.spc_source: Source | None = None
        self.inspections: list[InspectionRead] = [inspection()]
        self.inspections_total: int | None = None
        self.devices: list[DeviceStatus] = [device_status()]
        self.failure: Callable[[httpx.Request], httpx.Response] | None = None
        # Routes (without the /api/v1 prefix) that time out while the others answer.
        self.timing_out: set[str] = set()

    def _summary(self, request: httpx.Request) -> MetricsSummary:
        if request.url.params.get("source") == "simulated":
            return self.summary_simulated
        return self.summary_live

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure is not None:
            return self.failure(request)
        path = request.url.path.removeprefix(api.API_PREFIX)
        if path in self.timing_out:
            raise httpx.ReadTimeout("timed out", request=request)
        if path == "/metrics/summary":
            return httpx.Response(200, json=self._summary(request).model_dump(mode="json"))
        if path == "/metrics/timeseries":
            return httpx.Response(200, json=[p.model_dump(mode="json") for p in self.timeseries])
        if path == "/metrics/spc":
            source = self.spc_source or Source(request.url.params["source"])
            body = self.spc.model_copy(update={"source": source})
            return httpx.Response(200, json=body.model_dump(mode="json"))
        if path == "/inspections":
            limit = int(request.url.params["limit"])
            offset = int(request.url.params["offset"])
            total = self.inspections_total
            page = Page[InspectionRead](
                items=self.inspections,
                total=len(self.inspections) if total is None else total,
                limit=limit,
                offset=offset,
            )
            return httpx.Response(200, json=page.model_dump(mode="json"))
        if path == "/devices":
            return httpx.Response(200, json=[d.model_dump(mode="json") for d in self.devices])
        return httpx.Response(404, json={"detail": "Not Found"})

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    def to(self, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == api.API_PREFIX + path]


class MissingSecrets:
    """Behaves like ``st.secrets`` without a secrets file."""

    def __contains__(self, key: object) -> bool:
        raise FileNotFoundError("No secrets found")

    def __getitem__(self, key: str) -> object:
        raise FileNotFoundError("No secrets found")


@pytest.fixture(autouse=True)
def _no_local_secrets_file(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Author tests never read a local ``.streamlit/secrets.toml`` (SPEC-028 §4.6).

    The README recommends that file at the repository root, which is also where pytest runs;
    Streamlit would read it, and the tests would depend on the machine. The acceptance tests
    (``tests/acceptance/``, the tester's) keep their own isolation and are not touched.
    """
    if "acceptance" in request.node.path.parts:
        return
    monkeypatch.setattr(st, "secrets", MissingSecrets())


@pytest.fixture(autouse=True)
def _clear_streamlit_caches() -> Iterator[None]:
    st.cache_data.clear()
    st.cache_resource.clear()
    yield
    st.cache_data.clear()
    st.cache_resource.clear()


@pytest.fixture
def no_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def mock_api(monkeypatch: pytest.MonkeyPatch, no_config_env: None) -> MockApi:
    """A ``MockApi`` behind ``api.get_client()``."""
    mock = MockApi()
    client = api.ApiClient(BASE_URL, new_key(), transport=httpx.MockTransport(mock.handler))
    monkeypatch.setattr(api, "get_client", lambda: client)
    return mock


@pytest.fixture
def factory() -> SimpleNamespace:
    """Model builders and paths (test modules cannot import ``conftest`` in importlib mode)."""
    return SimpleNamespace(
        summary=summary,
        inspection=inspection,
        spc_point=spc_point,
        spc_response=spc_response,
        device_status=device_status,
        metrics_document=metrics_document,
        new_key=new_key,
        MockApi=MockApi,
        base_url=BASE_URL,
        views=VIEWS_DIR,
        app=APP_FILE,
    )
