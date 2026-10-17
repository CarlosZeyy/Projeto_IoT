"""Acceptance tests for SPEC-014 (``scripts/simulate.py``: simulated lot generator).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test per CA (``test_caNN_*``); ``test_extra_*`` tests are exploratory edge
cases around SPEC-014 section 4 that no CA spells out.

Common context (SPEC-014 section 5): the script is loaded with
``importlib.util.spec_from_file_location`` and driven through
``main([...], transport=MockTransport(...), sleep=<recorder>, now=<fixed>)``. The fake API keeps
the inserted ids in a ``dict`` and answers ``created``/``duplicate`` like SPEC-004. No real
network: every request goes to an ``httpx.MockTransport``. The device key is generated at run
time and never written as a literal (R-03); the API URL has no credentials.

The only database test (``test_extra_real_api_is_idempotent``, marker ``db``) forwards the mock
transport to the real ``qc_api`` app inside a ``TestClient`` on the ``clean_db`` fixture.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import random
import re
import secrets
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

import qc_contracts
from qc_contracts import InspectionCreate, ObjectType, Source, is_defective

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "simulate.py"

API_URL = "https://api.partqc.test"
URL_HEALTH = "/api/v1/health"
URL_BATCH = "/api/v1/inspections/batch"

# Fixed clock of CA-01 (after the last generated item, so CA-09 is not triggered).
NOW = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)
CA01_ARGS = [
    "--dry-run",
    "--seed",
    "42",
    "--lots",
    "3",
    "--lot-size",
    "10",
    "--start",
    "2026-10-01T12:00:00Z",
    "--device-id",
    "sim-01",
]

# The keys of docs/architecture.md section 3.2 (R-04).
CONTRACT_KEYS = {
    "inspection_id",
    "device_id",
    "lot_id",
    "inspected_at",
    "object_type",
    "grade",
    "grade_score",
    "type_confidence",
    "grade_confidence",
    "needs_review",
    "model_version",
    "model_sha256",
    "latency_ms",
    "source",
}

GRADE_INDEX = {"perfect": 0, "good": 1, "fair": 2, "poor": 3, "unusable": 4}
LOT_RE = re.compile(r"^SIM-(\d{8})-(\d{3})$")


# --------------------------------------------------------------------------- loading


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("simulate_spec014_acceptance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sim = _load_script()


# --------------------------------------------------------------------------- fake API


Action = int | Exception | Callable[[httpx.Request], httpx.Response]


class FakeApi:
    """Fake cloud API with the SPEC-004 idempotency (ids in a ``dict``).

    ``health`` and ``batch_script`` hold scripted actions consumed one per request: an ``int``
    status (2xx processes the batch with that status, anything else returns it with a
    ``{"detail": ...}`` body), an exception to raise, or a callable returning a response.
    When the script is empty, the batch is processed with status 200.
    """

    def __init__(self, key: str) -> None:
        self.key = key
        self.store: dict[str, dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []
        self.health: list[Action] = []
        self.batch_script: list[Action] = []
        self.detail_for: dict[int, Any] = {
            401: "Missing or invalid API key",
            403: "device_id does not match API key",
            422: "x",
            500: "boom",
            503: "Database unavailable",
        }

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def batch_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "POST" and r.url.path == URL_BATCH]

    def _status(self, status: int) -> httpx.Response:
        return httpx.Response(status, json={"detail": self.detail_for.get(status, "error")})

    def handler(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path == URL_HEALTH:
            if self.health:
                action = self.health.pop(0)
                if isinstance(action, Exception):
                    raise action
                if callable(action):
                    return action(request)
                if action != 200:
                    return httpx.Response(
                        action,
                        json={
                            "status": "degraded",
                            "db": "error",
                            "api_version": "0.1.0",
                            "contract_version": qc_contracts.__version__,
                        },
                    )
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "db": "ok",
                    "api_version": "0.1.0",
                    "contract_version": qc_contracts.__version__,
                },
            )
        if request.method == "POST" and path == URL_BATCH:
            status = 200
            if self.batch_script:
                action = self.batch_script.pop(0)
                if isinstance(action, Exception):
                    raise action
                if callable(action):
                    return action(request)
                if not 200 <= action < 300:
                    return self._status(action)
                status = action
            return self._ingest(request, status)
        return httpx.Response(404, json={"detail": "Not Found"})

    def _ingest(self, request: httpx.Request, status: int) -> httpx.Response:
        if request.headers.get("X-API-Key") != self.key:
            return self._status(401)
        body = json.loads(request.content)
        batch = qc_contracts.BatchCreate.model_validate(body)
        results = []
        for item in batch.items:
            key = str(item.inspection_id)
            if key in self.store:
                results.append({"inspection_id": key, "status": "duplicate"})
            else:
                self.store[key] = item.model_dump(mode="json")
                results.append({"inspection_id": key, "status": "created"})
        return httpx.Response(status, json={"results": results})


def _refuse_all(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
    raise AssertionError(f"unexpected request: {request.method} {request.url}")


# --------------------------------------------------------------------------- running


@dataclass
class Run:
    code: int
    out: str
    err: str
    sleeps: list[float] = field(default_factory=list)

    def items(self) -> list[InspectionCreate]:
        return [InspectionCreate.model_validate_json(line) for line in self.out.splitlines()]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CLOUD_API_URL", "SIM_DEVICE_ID", "SIM_DEVICE_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def new_key() -> str:
    """Random device key; starts with a letter so argparse never reads it as an option."""
    return "k" + secrets.token_urlsafe(24)


@pytest.fixture
def key() -> str:
    return new_key()


@pytest.fixture
def run(capsys: pytest.CaptureFixture[str]) -> Callable[..., Run]:
    def _run(
        argv: list[str],
        *,
        api: FakeApi | None = None,
        now: datetime | None = NOW,
    ) -> Run:
        sleeps: list[float] = []
        transport = api.transport if api is not None else httpx.MockTransport(_refuse_all)
        capsys.readouterr()
        code = sim.main(argv, transport=transport, sleep=sleeps.append, now=now)
        out, err = capsys.readouterr()
        return Run(code, out, err, sleeps)

    return _run


def send_args(key: str, *extra: str) -> list[str]:
    return [
        "--api-url",
        API_URL,
        "--api-key",
        key,
        "--device-id",
        "sim-01",
        *extra,
    ]


def by_lot(items: list[InspectionCreate]) -> dict[str, list[InspectionCreate]]:
    lots: dict[str, list[InspectionCreate]] = defaultdict(list)
    for item in items:
        lots[item.lot_id].append(item)
    return dict(lots)


def summary_fields(text: str) -> dict[str, str]:
    """``key=value`` pairs of the last line of ``text`` that contains ``source=``."""
    lines = [line for line in text.splitlines() if "source=" in line]
    assert lines, text
    return dict(pair.split("=", 1) for pair in lines[-1].split() if "=" in pair)


def dry(seed: int, *extra: str) -> list[str]:
    return ["--dry-run", "--device-id", "sim-01", "--seed", str(seed), *extra]


# --------------------------------------------------------------------------- CA-01


def test_ca01_dry_run_prints_valid_simulated_items(run: Callable[..., Run]) -> None:
    result = run(CA01_ARGS)

    assert result.code == 0, result.err
    lines = result.out.splitlines()
    assert len(lines) == 30
    items = [InspectionCreate.model_validate_json(line) for line in lines]
    for raw, item in zip(lines, items, strict=True):
        assert json.loads(raw)["source"] == "simulated"
        assert item.source is Source.SIMULATED
        assert item.model_version == "sim-v0"
        assert item.model_sha256 == "0" * 64
        assert item.device_id == "sim-01"
    lots = Counter(item.lot_id for item in items)
    assert lots == {"SIM-20261001-001": 10, "SIM-20261001-002": 10, "SIM-20261001-003": 10}
    # Items come out lot by lot, in order.
    assert [item.lot_id for item in items] == sorted(item.lot_id for item in items)
    times = [item.inspected_at for item in items]
    assert all(a < b for a, b in zip(times, times[1:], strict=False)), times
    assert all(t.tzinfo is not None and t.utcoffset() == timedelta(0) for t in times)


def test_ca01_dry_run_makes_no_request(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    result = run(CA01_ARGS, api=api)

    assert result.code == 0, result.err
    assert api.requests == []
    assert result.sleeps == []


# --------------------------------------------------------------------------- CA-02


def test_ca02_same_seed_same_bytes_other_seed_other_ids(run: Callable[..., Run]) -> None:
    first = run(CA01_ARGS)
    second = run(CA01_ARGS)
    other_args = [a if a != "42" else "43" for a in CA01_ARGS]
    other = run(other_args)

    assert first.code == second.code == other.code == 0
    assert first.out.encode() == second.out.encode()
    assert first.out  # not trivially equal

    ids = [item.inspection_id for item in first.items()]
    other_ids = [item.inspection_id for item in other.items()]
    assert len(set(ids)) == len(ids) == 30
    assert len(set(other_ids)) == len(other_ids) == 30
    assert not set(ids) & set(other_ids)
    assert all(uuid.UUID(str(i)).version == 4 for i in ids + other_ids)


# --------------------------------------------------------------------------- CA-03 (R-06)


@pytest.mark.parametrize(
    "source_args",
    [["--source", "live"], ["--source=live"], ["--source", "simulated"]],
    ids=["space", "equals", "even-simulated"],
)
def test_ca03_source_argument_is_unknown(
    run: Callable[..., Run], key: str, source_args: list[str]
) -> None:
    api = FakeApi(key)
    result = run([*CA01_ARGS, *source_args], api=api)

    assert result.code == 2
    assert result.out == ""
    assert api.requests == []
    assert result.err.strip()  # message on stderr


def test_ca03_source_argument_is_refused_when_sending(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    result = run(send_args(key, "--source", "live", "--lots", "1", "--lot-size", "5"), api=api)

    assert result.code == 2
    assert api.requests == []
    assert api.store == {}


def test_ca03_thousand_items_with_valid_combinations_are_simulated(
    run: Callable[..., Run], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Environment variables that a careless implementation could read must not matter.
    monkeypatch.setenv("SOURCE", "live")
    monkeypatch.setenv("SIM_SOURCE", "live")
    rng = random.Random(14)
    total = 0
    combos = 0
    while total < 1000 or combos < 25:
        lots = rng.randint(1, 12)
        extra: list[str] = ["--lots", str(lots)]
        if rng.random() < 0.5:
            extra += ["--lot-size", str(rng.randint(1, 60))]
        else:
            low = rng.randint(1, 30)
            extra += ["--lot-size-min", str(low), "--lot-size-max", str(rng.randint(low, 60))]
        extra += ["--defect-rate", str(rng.choice([0, 0.05, 0.1, 0.5, 1]))]
        extra += ["--unknown-rate", str(rng.choice([0, 0.02, 0.5, 1]))]
        if lots > 1 and rng.random() < 0.5:
            chosen = rng.sample(range(1, lots + 1), rng.randint(1, min(3, lots)))
            extra += ["--out-of-control-lots", ",".join(map(str, chosen))]
        if rng.random() < 0.5:
            extra += ["--model-version", rng.choice(["sim-v0", "sim.v1", "abc"])]
        if rng.random() < 0.5:
            extra += ["--start", "2026-09-30T08:15:00-03:00"]
        result = run(dry(rng.randint(0, 2**32 - 1), *extra))
        assert result.code == 0, (extra, result.err)
        for line in result.out.splitlines():
            assert json.loads(line)["source"] == "simulated"
            assert InspectionCreate.model_validate_json(line).source is Source.SIMULATED
            total += 1
        combos += 1
    assert total >= 1000


def test_ca03_generate_returns_only_simulated_items() -> None:
    cfg = sim.parse_args(
        [
            "--dry-run",
            "--device-id",
            "sim-01",
            "--seed",
            "5",
            "--lots",
            "4",
            "--lot-size",
            "250",
            "--start",
            "2026-10-01T00:00:00Z",
        ]
    )
    items = sim.generate(cfg)

    assert len(items) == 1000
    assert all(isinstance(item, InspectionCreate) for item in items)
    assert {item.source for item in items} == {Source.SIMULATED}


# --------------------------------------------------------------------------- CA-04


def test_ca04_grade_distribution(run: Callable[..., Run]) -> None:
    result = run(
        dry(1, "--lots", "20", "--lot-size", "500", "--defect-rate", "0.2", "--unknown-rate", "0")
    )

    assert result.code == 0, result.err
    items = result.items()
    assert len(items) == 10_000
    assert all(item.object_type is not ObjectType.UNKNOWN for item in items)
    defective = [item for item in items if is_defective(item.grade)]
    good = [item for item in items if not is_defective(item.grade)]
    assert abs(len(defective) / len(items) - 0.20) <= 0.02

    poor = sum(1 for item in defective if item.grade == "poor")
    assert {item.grade.value for item in defective} <= {"poor", "unusable"}
    assert abs(poor / len(defective) - 0.70) <= 0.04

    counts = Counter(item.grade.value for item in good)
    assert set(counts) <= {"perfect", "good", "fair"}
    for grade, expected in (("perfect", 0.40), ("good", 0.35), ("fair", 0.25)):
        assert abs(counts[grade] / len(good) - expected) <= 0.03, (grade, counts)


# --------------------------------------------------------------------------- CA-05


def test_ca05_unknown_fraction_and_nulls(run: Callable[..., Run]) -> None:
    result = run(dry(2, "--lots", "10", "--lot-size", "200", "--unknown-rate", "0.1"))

    assert result.code == 0, result.err
    items = result.items()
    assert len(items) == 2000
    unknown = [item for item in items if item.object_type is ObjectType.UNKNOWN]
    assert abs(len(unknown) / len(items) - 0.10) <= 0.03
    for item in unknown:
        assert item.grade is None
        assert item.grade_score is None
        assert item.grade_confidence is None
        assert item.type_confidence < 0.70
    raw_unknown = [json.loads(line) for line in result.out.splitlines()]
    raw_unknown = [r for r in raw_unknown if r["object_type"] == "unknown"]
    assert all(
        r["grade"] is None and r["grade_score"] is None and r["grade_confidence"] is None
        for r in raw_unknown
    )


# --------------------------------------------------------------------------- CA-06


def test_ca06_random_lot_sizes_stay_in_range(run: Callable[..., Run]) -> None:
    result = run(dry(3, "--lots", "5", "--lot-size-min", "3", "--lot-size-max", "8"))

    assert result.code == 0, result.err
    lots = by_lot(result.items())
    assert len(lots) == 5
    assert all(3 <= len(items) <= 8 for items in lots.values()), {
        k: len(v) for k, v in lots.items()
    }


@pytest.mark.parametrize(
    "extra",
    [
        ["--lot-size-min", "9", "--lot-size-max", "8"],
        ["--lot-size", "10", "--lot-size-min", "3", "--lot-size-max", "8"],
    ],
    ids=["min-above-max", "exclusive-with-lot-size"],
)
def test_ca06_invalid_lot_size_combinations_exit_2(
    run: Callable[..., Run], extra: list[str]
) -> None:
    result = run(dry(3, "--lots", "5", *extra))

    assert result.code == 2
    assert result.out == ""
    assert result.err.strip()


# --------------------------------------------------------------------------- CA-07 (SPC)


def test_ca07_out_of_control_lots_on_the_p_chart(run: Callable[..., Run]) -> None:
    from qc_api.services.spc import LotCounts, compute_p_chart

    result = run(
        dry(
            42,
            "--lots",
            "30",
            "--lot-size",
            "200",
            "--defect-rate",
            "0.1",
            "--unknown-rate",
            "0",
            "--out-of-control-lots",
            "24,28",
        )
    )
    assert result.code == 0, result.err

    lots = []
    for lot_id, items in by_lot(result.items()).items():
        known = [item for item in items if item.object_type is not ObjectType.UNKNOWN]
        lots.append(
            LotCounts(
                lot_id=lot_id,
                started_at=min(item.inspected_at for item in known),
                ended_at=max(item.inspected_at for item in known),
                n=len(known),
                defects=sum(1 for item in known if is_defective(item.grade)),
            )
        )
    assert len(lots) == 30
    chart = compute_p_chart(lots, baseline_lots=20, min_lot_size=5)

    assert len(chart.points) == 30
    flagged = {p.lot_id[-3:] for p in chart.points if p.out_of_control}
    assert {"024", "028"} <= flagged, flagged
    assert len(flagged - {"024", "028"}) <= 2, flagged


# --------------------------------------------------------------------------- CA-08


@pytest.mark.parametrize(
    "extra",
    [
        ["--out-of-control-lots", "0,3"],
        ["--out-of-control-lots", "11"],
        ["--out-of-control-lots", "a,b"],
        ["--out-of-control-lots", "3,3"],
        ["--defect-rate", "1.5"],
        ["--unknown-rate", "-0.1"],
        ["--device-id", "sim-01\n"],
        ["--model-version", "sim-v0\n"],
    ],
    ids=[
        "ooc-zero",
        "ooc-above-lots",
        "ooc-not-numbers",
        "ooc-repeated",
        "defect-rate-above-1",
        "unknown-rate-negative",
        "device-id-newline",
        "model-version-newline",
    ],
)
def test_ca08_invalid_arguments_exit_2(run: Callable[..., Run], key: str, extra: list[str]) -> None:
    api = FakeApi(key)
    dry_result = run(["--dry-run", "--seed", "1", "--lots", "10", "--device-id", "sim-01", *extra])
    send_result = run(send_args(key, "--seed", "1", "--lots", "10", *extra), api=api)

    assert dry_result.code == 2
    assert dry_result.out == ""
    assert dry_result.err.strip()
    assert send_result.code == 2
    assert api.requests == []


# --------------------------------------------------------------------------- CA-09


def test_ca09_start_in_the_future_exits_2_without_requests(
    run: Callable[..., Run], key: str
) -> None:
    start = (NOW + timedelta(hours=1)).isoformat()
    api = FakeApi(key)
    sent = run(send_args(key, "--seed", "1", "--lots", "2", "--start", start), api=api)
    dry_run = run(dry(1, "--lots", "2", "--start", start))

    assert sent.code == 2
    assert api.requests == []
    assert dry_run.code == 2
    assert dry_run.out == ""


# --------------------------------------------------------------------------- CA-10 (R-05)


def test_ca10_send_then_resend_is_idempotent(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    argv = send_args(key, "--seed", "42", "--lots", "10", "--lot-size", "25")

    first = run(argv, api=api)

    assert first.code == 0, first.err
    assert [(r.method, r.url.path) for r in api.requests] == [
        ("GET", URL_HEALTH),
        ("POST", URL_BATCH),
        ("POST", URL_BATCH),
        ("POST", URL_BATCH),
    ]
    sizes = [len(json.loads(r.content)["items"]) for r in api.batch_requests()]
    assert sizes == [100, 100, 50]
    assert all(r.headers.get("X-API-Key") == key for r in api.batch_requests())
    assert "sent=250 created=250 duplicate=0" in first.out
    fields = summary_fields(first.out)
    assert fields["lots"] == "10"
    assert fields["seed"] == "42"
    assert fields["source"] == "simulated"
    assert len(api.store) == 250

    api.requests.clear()
    second = run(argv, api=api)

    assert second.code == 0, second.err
    assert "sent=250 created=0 duplicate=250" in second.out
    assert len(api.store) == 250
    assert len(api.batch_requests()) == 3


# --------------------------------------------------------------------------- CA-11


def test_ca11_retries_then_success(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    api.batch_script = [503, httpx.ConnectError("connection refused"), 201]
    result = run(send_args(key, "--seed", "42", "--lots", "10", "--lot-size", "25"), api=api)

    assert result.code == 0, result.err
    assert result.sleeps == [2, 4]
    assert len(api.store) == 250
    assert "sent=250 created=250 duplicate=0" in result.out
    # 3 attempts for the first batch, then 2 more batches.
    assert len(api.batch_requests()) == 5
    first_bodies = [r.content for r in api.batch_requests()[:3]]
    assert first_bodies[0] == first_bodies[1] == first_bodies[2]


# --------------------------------------------------------------------------- CA-12


def test_ca12_retries_exhausted_exit_5(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    api.batch_script = [503] * 10
    result = run(send_args(key, "--seed", "42", "--lots", "10", "--lot-size", "25"), api=api)

    assert result.code == 5
    assert result.sleeps == [2, 4, 8]
    assert len(api.batch_requests()) == 4
    assert api.store == {}
    assert key not in result.out + result.err


# --------------------------------------------------------------------------- CA-13


@pytest.mark.parametrize("status", [401, 403])
def test_ca13_auth_failure_exit_3_no_more_requests_no_key(
    run: Callable[..., Run],
    key: str,
    status: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    api = FakeApi(key)
    api.batch_script = [status] * 10
    result = run(send_args(key, "--seed", "42", "--lots", "10", "--lot-size", "25"), api=api)

    assert result.code == 3
    assert [(r.method, r.url.path) for r in api.requests] == [
        ("GET", URL_HEALTH),
        ("POST", URL_BATCH),
    ]
    assert result.sleeps == []
    assert key not in result.out
    assert key not in result.err
    assert key not in caplog.text
    assert all(key not in rec.getMessage() for rec in caplog.records)


# --------------------------------------------------------------------------- CA-14


def test_ca14_422_exit_4_with_detail(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    api.batch_script = [422]
    result = run(send_args(key, "--seed", "42", "--lots", "1", "--lot-size", "5"), api=api)

    assert result.code == 4
    assert "x" in result.err
    assert result.sleeps == []
    assert len(api.batch_requests()) == 1

    # Same CA with a detail that cannot appear by chance in any message.
    marker = f"detail-{secrets.token_hex(6)}"
    api2 = FakeApi(key)
    api2.detail_for[422] = marker
    api2.batch_script = [422]
    result2 = run(send_args(key, "--seed", "42", "--lots", "1", "--lot-size", "5"), api=api2)

    assert result2.code == 4
    assert marker in result2.err


# --------------------------------------------------------------------------- CA-15


def test_ca15_missing_key_exits_2_without_requests(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    result = run(["--api-url", API_URL, "--device-id", "sim-01", "--seed", "1"], api=api)

    assert result.code == 2
    assert api.requests == []
    assert result.err.strip()


def test_ca15_plain_http_remote_url_exits_2(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    argv = ["--api-url", "http://api.exemplo.org", "--api-key", key, "--device-id", "sim-01"]
    result = run(argv, api=api)

    assert result.code == 2
    assert api.requests == []
    assert key not in result.out + result.err


def test_ca15_local_http_url_is_accepted(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    argv = [
        "--api-url",
        "http://127.0.0.1:8001",
        "--api-key",
        key,
        "--device-id",
        "sim-01",
        "--seed",
        "7",
        "--lots",
        "2",
        "--lot-size",
        "5",
    ]
    result = run(argv, api=api)

    assert result.code == 0, result.err
    assert "sent=10 created=10 duplicate=0" in result.out
    assert {(r.url.host, r.url.port) for r in api.requests} == {("127.0.0.1", 8001)}
    assert api.requests[0].url.path == URL_HEALTH


# --------------------------------------------------------------------------- CA-16 (R-04)


def test_ca16_batch_items_have_exactly_the_contract_keys(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    result = run(
        send_args(
            key,
            "--seed",
            "16",
            "--lots",
            "6",
            "--lot-size-min",
            "10",
            "--lot-size-max",
            "40",
            "--unknown-rate",
            "0.3",
        ),
        api=api,
    )

    assert result.code == 0, result.err
    batches = api.batch_requests()
    assert batches
    seen_unknown = seen_known = False
    for request in batches:
        body = json.loads(request.content)
        assert set(body) == {"items"}
        assert 1 <= len(body["items"]) <= 100
        for item in body["items"]:
            assert set(item) == CONTRACT_KEYS
            seen_unknown |= item["object_type"] == "unknown"
            seen_known |= item["object_type"] != "unknown"
    assert seen_unknown and seen_known


# --------------------------------------------------------------------------- exploratory


def test_extra_dry_run_summary_goes_to_stderr(run: Callable[..., Run]) -> None:
    result = run(CA01_ARGS)

    fields = summary_fields(result.err)
    assert fields["seed"] == "42"
    assert fields["lots"] == "3"
    assert fields["source"] == "simulated"
    assert "created" not in fields and "duplicate" not in fields
    assert "source=" not in result.out.replace('"source":"simulated"', "")


def test_extra_random_seed_is_printed_and_reproducible(run: Callable[..., Run]) -> None:
    base = ["--dry-run", "--device-id", "sim-01", "--lots", "2", "--lot-size", "4"]
    base += ["--start", "2026-10-01T12:00:00Z"]
    first = run(base)
    assert first.code == 0, first.err
    seed = summary_fields(first.err)["seed"]
    assert re.fullmatch(r"\d+", seed)
    assert 0 <= int(seed) < 2**32

    again = run([*base, "--seed", seed])
    assert again.out == first.out


def test_extra_same_seed_other_start_same_ids(run: Callable[..., Run], key: str) -> None:
    a = run(dry(9, "--lots", "2", "--lot-size", "5", "--start", "2026-10-01T12:00:00Z"))
    b = run(dry(9, "--lots", "2", "--lot-size", "5", "--start", "2026-09-20T06:00:00Z"))

    ids_a = [i.inspection_id for i in a.items()]
    ids_b = [i.inspection_id for i in b.items()]
    assert ids_a == ids_b
    assert {i.lot_id for i in b.items()} == {"SIM-20260920-001", "SIM-20260920-002"}

    api = FakeApi(key)
    base = send_args(key, "--seed", "9", "--lots", "2", "--lot-size", "5")
    run([*base, "--start", "2026-10-01T12:00:00Z"], api=api)
    resend = run([*base, "--start", "2026-09-20T06:00:00Z"], api=api)
    assert "sent=10 created=0 duplicate=10" in resend.out
    assert len(api.store) == 10


def test_extra_lot_timing_and_utc_date(run: Callable[..., Run]) -> None:
    # 22:00 at -03:00 is 01:00 UTC of the next day: the lot id uses the UTC date.
    result = run(dry(4, "--lots", "3", "--lot-size", "4", "--start", "2026-09-30T22:00:00-03:00"))
    assert result.code == 0, result.err
    start = datetime(2026, 10, 1, 1, 0, tzinfo=UTC)
    lots = by_lot(result.items())
    assert sorted(lots) == ["SIM-20261001-001", "SIM-20261001-002", "SIM-20261001-003"]
    for i, lot_id in enumerate(sorted(lots), start=1):
        lot_start = start + (i - 1) * timedelta(minutes=10)
        times = [item.inspected_at for item in lots[lot_id]]
        assert times[0] == lot_start
        assert all(lot_start <= t < lot_start + timedelta(minutes=10) for t in times)
        gaps = {b - a for a, b in zip(times, times[1:], strict=False)}
        assert gaps == {timedelta(minutes=10) / 4}


def test_extra_default_start_is_now_minus_lots_times_10_min(run: Callable[..., Run]) -> None:
    result = run(dry(4, "--lots", "6", "--lot-size", "3"))
    assert result.code == 0, result.err
    first = result.items()[0]
    assert first.inspected_at == NOW - timedelta(minutes=60)
    assert first.lot_id == "SIM-20261001-001"


def test_extra_start_limit_is_inclusive_at_now_plus_5_min(run: Callable[..., Run]) -> None:
    base = dry(1, "--lots", "1", "--lot-size", "1")
    at_limit = run([*base, "--start", "2026-10-01T13:05:00Z"])
    past_limit = run([*base, "--start", "2026-10-01T13:05:00.000001Z"])

    assert at_limit.code == 0, at_limit.err
    assert past_limit.code == 2
    assert past_limit.out == ""


@pytest.mark.parametrize(
    ("start", "lot_date"),
    [
        ("2026-10-01T12:00:00+14:00", "20260930"),
        ("2026-09-30T23:30:00-05:00", "20261001"),
        ("2026-10-01T12:00Z", "20261001"),
    ],
)
def test_extra_lot_date_is_the_utc_date_of_start(
    run: Callable[..., Run], start: str, lot_date: str
) -> None:
    result = run(dry(1, "--lots", "2", "--lot-size", "2", "--start", start))
    assert result.code == 0, result.err
    assert {i.lot_id for i in result.items()} == {f"SIM-{lot_date}-001", f"SIM-{lot_date}-002"}


@pytest.mark.parametrize(
    "start", ["9999-12-31T23:00:00+00:00", "0001-01-01T00:00:00+05:00", "+2026-10-01T12:00:00Z"]
)
def test_extra_out_of_range_start_exits_2(run: Callable[..., Run], start: str) -> None:
    result = run(dry(1, "--lots", "2", "--lot-size", "2", "--start", start))
    assert result.code == 2
    assert result.out == ""


def test_extra_item_rules(run: Callable[..., Run]) -> None:
    result = run(dry(11, "--lots", "8", "--lot-size", "250", "--unknown-rate", "0.2"))
    assert result.code == 0, result.err
    for item in result.items():
        assert 40 <= item.latency_ms <= 180
        if item.object_type is ObjectType.UNKNOWN:
            assert 0.30 <= item.type_confidence <= 0.69
        else:
            assert item.object_type in (ObjectType.SCREW, ObjectType.NUT)
            assert 0.75 <= item.type_confidence <= 0.99
            assert 0.55 <= item.grade_confidence <= 0.95
            assert 0.0 <= item.grade_score <= 4.0
            assert abs(item.grade_score - GRADE_INDEX[item.grade.value]) <= 0.4 + 1e-9
        expected_review = item.type_confidence < 0.80 or (
            item.grade_confidence is not None and item.grade_confidence < 0.60
        )
        assert item.needs_review is expected_review
    types = Counter(
        i.object_type for i in result.items() if i.object_type is not ObjectType.UNKNOWN
    )
    assert abs(types[ObjectType.SCREW] / sum(types.values()) - 0.5) <= 0.05


def test_extra_out_of_control_rate_is_capped_at_one(run: Callable[..., Run]) -> None:
    result = run(
        dry(5, "--lots", "3", "--lot-size", "200", "--defect-rate", "0.5")
        + ["--unknown-rate", "0", "--out-of-control-lots", "2"]
    )
    assert result.code == 0, result.err
    lots = by_lot(result.items())
    assert all(is_defective(i.grade) for i in lots["SIM-20261001-002"])
    for lot_id in ("SIM-20261001-001", "SIM-20261001-003"):
        rate = sum(is_defective(i.grade) for i in lots[lot_id]) / len(lots[lot_id])
        assert 0.35 <= rate <= 0.65


@pytest.mark.parametrize(
    ("extra", "check"),
    [
        (["--defect-rate", "0", "--unknown-rate", "0", "--out-of-control-lots", "1"], "none"),
        (["--defect-rate", "1", "--unknown-rate", "0"], "all"),
        (["--unknown-rate", "1"], "unknown"),
    ],
    ids=["no-defects", "all-defects", "all-unknown"],
)
def test_extra_extreme_rates(run: Callable[..., Run], extra: list[str], check: str) -> None:
    result = run(dry(6, "--lots", "2", "--lot-size", "50", *extra))
    assert result.code == 0, result.err
    items = result.items()
    if check == "none":
        assert not any(is_defective(i.grade) for i in items)
    elif check == "all":
        assert all(is_defective(i.grade) for i in items)
    else:
        assert all(i.object_type is ObjectType.UNKNOWN for i in items)


@pytest.mark.parametrize(
    "extra",
    [
        ["--lots", "0"],
        ["--lots", "501"],
        ["--lot-size", "0"],
        ["--lot-size", "1001"],
        ["--lot-size-min", "3"],
        ["--lot-size-max", "8"],
        ["--lot-size-min", "0", "--lot-size-max", "8"],
        ["--lot-size-min", "3", "--lot-size-max", "1001"],
        ["--seed", "-1"],
        ["--seed", "abc"],
        ["--start", "2026-10-01T12:00:00"],
        ["--start", "yesterday"],
        ["--device-id", "sím-01"],
        ["--device-id", "SIM-01"],
        ["--device-id", "ab"],
        ["--model-version", "SIM-V0"],
        ["--model-version", "v0"],
        ["--defect-rate", "nan"],
        ["--unknown-rate", "1.01"],
        ["--out-of-control-lots", "3,"],
        ["--out-of-control-lots", "-3"],
        ["--sour", "live"],
    ],
)
def test_extra_more_invalid_arguments_exit_2(run: Callable[..., Run], extra: list[str]) -> None:
    result = run(["--dry-run", "--device-id", "sim-01", "--lots", "10", "--seed", "1", *extra])
    assert result.code == 2
    assert result.out == ""


@pytest.mark.parametrize(
    "extra",
    [
        ["--lots", "1", "--lot-size", "1"],
        ["--lots", "500", "--lot-size", "1"],
        ["--lots", "1", "--lot-size", "1000"],
        ["--lots", "10", "--out-of-control-lots", "1,10"],
        ["--lots", "2", "--defect-rate", "0", "--unknown-rate", "0"],
        ["--lots", "2", "--defect-rate", "1", "--unknown-rate", "1"],
        ["--lots", "2", "--lot-size-min", "1", "--lot-size-max", "1000"],
        ["--lots", "2", "--model-version", "partqc.sim-2"],
        ["--lots", "2", "--seed", "0"],
    ],
)
def test_extra_boundary_arguments_are_accepted(run: Callable[..., Run], extra: list[str]) -> None:
    result = run(["--dry-run", "--device-id", "sim-01", "--seed", "1", *extra])
    assert result.code == 0, result.err


def test_extra_env_defaults(
    run: Callable[..., Run], key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOUD_API_URL", API_URL)
    monkeypatch.setenv("SIM_DEVICE_ID", "sim-02")
    monkeypatch.setenv("SIM_DEVICE_API_KEY", key)
    api = FakeApi(key)
    result = run(["--seed", "3", "--lots", "1", "--lot-size", "5"], api=api)

    assert result.code == 0, result.err
    assert {r.url.host for r in api.requests} == {"api.partqc.test"}
    assert {item["device_id"] for item in api.store.values()} == {"sim-02"}
    assert key not in result.out + result.err


def test_extra_missing_url_exits_2(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    result = run(["--api-key", key, "--device-id", "sim-01"], api=api)
    assert result.code == 2
    assert api.requests == []
    assert key not in result.out + result.err


@pytest.mark.parametrize(
    "url",
    ["ftp://api.partqc.test", "api.partqc.test", "http://localhost.evil.test", "https://"],
)
def test_extra_bad_urls_exit_2(run: Callable[..., Run], key: str, url: str) -> None:
    api = FakeApi(key)
    result = run(["--api-url", url, "--api-key", key, "--device-id", "sim-01"], api=api)
    assert result.code == 2
    assert api.requests == []


def test_extra_localhost_http_and_trailing_slash(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    argv = ["--api-url", "http://localhost:8001/", "--api-key", key, "--device-id", "sim-01"]
    result = run([*argv, "--seed", "1", "--lots", "1", "--lot-size", "3"], api=api)
    assert result.code == 0, result.err
    assert [r.url.path for r in api.requests] == [URL_HEALTH, URL_BATCH]


def test_extra_timeouts(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    result = run(send_args(key, "--seed", "1", "--lots", "1", "--lot-size", "3"), api=api)
    assert result.code == 0, result.err
    health, batch = api.requests
    assert health.extensions["timeout"]["read"] == 90
    assert batch.extensions["timeout"]["read"] == 10


@pytest.mark.parametrize(
    "failure",
    [503, 500, httpx.ConnectError("down"), httpx.ReadTimeout("slow")],
    ids=["503", "500", "connect-error", "read-timeout"],
)
def test_extra_health_failure_exits_5_without_batches(
    run: Callable[..., Run], key: str, failure: Action
) -> None:
    api = FakeApi(key)
    api.health = [failure] * 5
    result = run(send_args(key, "--seed", "1", "--lots", "1", "--lot-size", "3"), api=api)
    assert result.code == 5
    assert api.batch_requests() == []
    assert key not in result.out + result.err


@pytest.mark.parametrize(
    "failure",
    [500, 502, httpx.ReadTimeout("slow"), httpx.ConnectError("down")],
    ids=["500", "502", "read-timeout", "connect-error"],
)
def test_extra_other_transient_failures_are_retried(
    run: Callable[..., Run], key: str, failure: Action
) -> None:
    api = FakeApi(key)
    api.batch_script = [failure] * 4
    result = run(send_args(key, "--seed", "1", "--lots", "1", "--lot-size", "3"), api=api)
    assert result.code == 5
    assert result.sleeps == [2, 4, 8]
    assert len(api.batch_requests()) == 4


def test_extra_auth_failure_on_a_later_batch(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    api.batch_script = [200, 401]
    result = run(send_args(key, "--seed", "42", "--lots", "10", "--lot-size", "25"), api=api)
    assert result.code == 3
    assert len(api.batch_requests()) == 2
    assert len(api.store) == 100
    assert key not in result.out + result.err


def test_extra_422_with_list_detail(run: Callable[..., Run], key: str) -> None:
    api = FakeApi(key)
    api.detail_for[422] = [{"loc": ["body", "items", 0], "msg": "bad-item-marker"}]
    api.batch_script = [422]
    result = run(send_args(key, "--seed", "1", "--lots", "1", "--lot-size", "3"), api=api)
    assert result.code == 4
    assert "bad-item-marker" in result.err


def test_extra_key_never_printed_nor_logged_on_success(
    run: Callable[..., Run], key: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    api = FakeApi(key)
    result = run(send_args(key, "--seed", "2", "--lots", "3", "--lot-size", "40"), api=api)
    assert result.code == 0, result.err
    assert key not in result.out + result.err
    assert key not in caplog.text


def test_extra_help_mentions_env_var_and_no_source(
    capsys: pytest.CaptureFixture[str],
) -> None:
    try:
        code = sim.main(["--help"], transport=httpx.MockTransport(_refuse_all))
    except SystemExit as exc:  # pragma: no cover - argparse style is also acceptable
        code = exc.code
    out = capsys.readouterr().out
    assert code == 0
    assert "SIM_DEVICE_API_KEY" in out
    assert "--source" not in out


# --------------------------------------------------------------------------- real API (db)


@pytest.fixture
def real_api(clean_db: str) -> Iterator[tuple[httpx.MockTransport, str, str]]:
    import psycopg
    from fastapi.testclient import TestClient

    from qc_api.auth import hash_api_key
    from qc_api.config import Settings
    from qc_api.main import create_app

    device_key = new_key()
    with psycopg.connect(clean_db, autocommit=True, prepare_threshold=None) as conn:
        conn.execute(
            "insert into devices (device_id, api_key_hash) values (%s, %s)",
            ("sim-01", hash_api_key(device_key)),
        )
    app = create_app(Settings(DATABASE_URL=clean_db, READ_API_KEY=secrets.token_urlsafe(32)))
    with TestClient(app) as client:

        def forward(request: httpx.Request) -> httpx.Response:
            request.read()
            resp = client.request(
                request.method,
                request.url.path,
                content=request.content,
                headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            )
            return httpx.Response(resp.status_code, content=resp.content, headers=resp.headers)

        yield httpx.MockTransport(forward), device_key, clean_db


@pytest.mark.db
def test_extra_real_api_is_idempotent(
    real_api: tuple[httpx.MockTransport, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    import psycopg

    transport, device_key, conninfo = real_api
    argv = send_args(device_key, "--seed", "42", "--lots", "3", "--lot-size", "40")
    sleeps: list[float] = []

    assert sim.main(argv, transport=transport, sleep=sleeps.append, now=NOW) == 0
    assert "sent=120 created=120 duplicate=0" in capsys.readouterr().out
    assert sim.main(argv, transport=transport, sleep=sleeps.append, now=NOW) == 0
    assert "sent=120 created=0 duplicate=120" in capsys.readouterr().out
    assert sleeps == []

    with psycopg.connect(conninfo, autocommit=True, prepare_threshold=None) as conn:
        rows = conn.execute(
            "select count(*), count(distinct source), min(source::text) from inspections"
        ).fetchone()
    assert rows == (120, 1, "simulated")


@pytest.mark.db
def test_extra_real_api_wrong_key_exits_3(
    real_api: tuple[httpx.MockTransport, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    transport, _device_key, _conninfo = real_api
    wrong = new_key()
    argv = send_args(wrong, "--seed", "1", "--lots", "1", "--lot-size", "5")

    assert sim.main(argv, transport=transport, sleep=lambda _s: None, now=NOW) == 3
    captured = capsys.readouterr()
    assert wrong not in captured.out + captured.err
