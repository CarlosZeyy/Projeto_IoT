"""Author tests of ``scripts/simulate.py`` (SPEC-014).

The script is loaded with ``importlib`` (``scripts/`` is not a package). No real network: every
request goes to an ``httpx.MockTransport``; the ``db`` tests forward it to the real ``qc_api``
app in process. Dates are in the past of the real clock, because ``InspectionCreate`` checks
``inspected_at`` against it. The device key is generated at run time (R-03).
"""

import importlib.util
import json
import secrets
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from qc_api.auth import hash_api_key
from qc_api.config import Settings
from qc_api.services.spc import LotCounts, compute_p_chart
from qc_contracts import BatchCreate, Grade, InspectionCreate, ObjectType, is_defective

SCRIPT = Path(__file__).resolve().parents[1] / "simulate.py"
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
START = "2026-10-01T06:00:00Z"
API_URL = "https://api.example.test"
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


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("partqc_simulate_author", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sim = _load()


@pytest.fixture
def key() -> str:
    return "k-" + secrets.token_urlsafe(24)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CLOUD_API_URL", "SIM_DEVICE_ID", "SIM_DEVICE_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def online_env(monkeypatch: pytest.MonkeyPatch, key: str) -> str:
    monkeypatch.setenv("CLOUD_API_URL", API_URL)
    monkeypatch.setenv("SIM_DEVICE_ID", "sim-01")
    monkeypatch.setenv("SIM_DEVICE_API_KEY", key)
    return key


# ---------------------------------------------------------------------------------------------
# Fake API (idempotent by inspection_id, as in SPEC-004)
# ---------------------------------------------------------------------------------------------

Script = int | Exception | Callable[[httpx.Request], httpx.Response]


@dataclass
class FakeApi:
    health: Script = 200
    batch_script: list[Script] = field(default_factory=list)
    store: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == sim.HEALTH_PATH:
            return self._scripted(self.health, request) or httpx.Response(200, json={})
        assert request.url.path == sim.BATCH_PATH
        if self.batch_script:
            response = self._scripted(self.batch_script.pop(0), request)
            if response is not None:
                return response
        return self._ingest(request)

    @staticmethod
    def _scripted(step: Script, request: httpx.Request) -> httpx.Response | None:
        if isinstance(step, Exception):
            raise step
        if callable(step):
            return step(request)
        if step == 200:
            return None
        return httpx.Response(step, json={"detail": f"status {step}"})

    def _ingest(self, request: httpx.Request) -> httpx.Response:
        batch = BatchCreate.model_validate_json(request.content)
        results = []
        for item in batch.items:
            key = str(item.inspection_id)
            status = "duplicate" if key in self.store else "created"
            self.store.setdefault(key, item.model_dump(mode="json"))
            results.append({"inspection_id": key, "status": status})
        return httpx.Response(200, json={"results": results})

    @property
    def batch_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == sim.BATCH_PATH]


@dataclass
class Run:
    code: int
    out: str
    err: str
    sleeps: list[float]


@pytest.fixture
def run(capsys: pytest.CaptureFixture[str]) -> Callable[..., Run]:
    def _run(argv: list[str], api: FakeApi | None = None, now: datetime = NOW) -> Run:
        sleeps: list[float] = []
        transport = (api or FakeApi()).transport()
        code = sim.main(argv, transport=transport, sleep=sleeps.append, now=now)
        captured = capsys.readouterr()
        return Run(code, captured.out, captured.err, sleeps)

    return _run


def _dry(*extra: str) -> list[str]:
    return ["--dry-run", "--device-id", "sim-01", "--start", START, *extra]


def _cfg(*argv: str, now: datetime = NOW) -> Any:
    return sim.parse_args(["--device-id", "sim-01", "--dry-run", *argv], now=now)


def _items(*argv: str) -> list[InspectionCreate]:
    return sim.generate(_cfg(*argv))


# ---------------------------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------------------------


def test_defaults() -> None:
    cfg = _cfg(now=NOW)
    assert (cfg.lots, cfg.lot_size, cfg.lot_size_min, cfg.lot_size_max) == (10, 25, None, None)
    assert (cfg.defect_rate, cfg.unknown_rate) == (0.10, 0.02)
    assert cfg.out_of_control_lots == frozenset()
    assert cfg.model_version == "sim-v0"
    assert cfg.start == NOW - timedelta(minutes=100)
    assert 0 <= cfg.seed < 2**32
    assert cfg.api_url is None and cfg.api_key is None


def test_default_start_follows_lots_and_now_offset() -> None:
    now = datetime(2026, 10, 1, 6, 0, tzinfo=timezone(timedelta(hours=-3)))
    cfg = sim.parse_args(["--dry-run", "--device-id", "sim-01", "--lots", "3"], now=now)
    assert cfg.start == datetime(2026, 10, 1, 8, 30, tzinfo=UTC)
    assert cfg.start.tzinfo is UTC


def test_naive_now_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        sim.parse_args(["--dry-run", "--device-id", "sim-01"], now=datetime(2026, 10, 1))


def test_random_seed_is_printed(run: Callable[..., Run]) -> None:
    result = run(["--dry-run", "--device-id", "sim-01", "--lots", "1", "--lot-size", "2"])
    assert result.code == 0
    (summary,) = result.err.splitlines()
    seed = int(summary.split("seed=")[1].split()[0])
    assert 0 <= seed < 2**32


def test_env_defaults(online_env: str) -> None:
    cfg = sim.parse_args(["--start", START], now=NOW)
    assert (cfg.api_url, cfg.device_id, cfg.api_key) == (API_URL, "sim-01", online_env)


def test_options_override_env(online_env: str) -> None:
    cfg = sim.parse_args(
        [
            "--start",
            START,
            "--api-url",
            "http://127.0.0.1:8001/",
            "--device-id",
            "sim-02",
            "--api-key",
            "other-key",
        ],
        now=NOW,
    )
    assert (cfg.api_url, cfg.device_id, cfg.api_key) == (
        "http://127.0.0.1:8001",
        "sim-02",
        "other-key",
    )


def test_config_repr_hides_the_key(online_env: str) -> None:
    cfg = sim.parse_args(["--start", START], now=NOW)
    assert online_env not in repr(cfg)


@pytest.mark.parametrize(
    "argv",
    [
        ["--source", "live"],
        ["--source=live"],
        ["--source", "simulated"],
        ["--dry"],  # no prefix matching
        ["--lots", "0"],
        ["--lots", "501"],
        ["--lots", "x"],
        ["--lot-size", "0"],
        ["--lot-size", "1001"],
        ["--lot-size-min", "3"],
        ["--lot-size-max", "8"],
        ["--lot-size-min", "9", "--lot-size-max", "8"],
        ["--lot-size-min", "0", "--lot-size-max", "8"],
        ["--lot-size-min", "3", "--lot-size-max", "1001"],
        ["--lot-size", "10", "--lot-size-min", "3", "--lot-size-max", "8"],
        ["--defect-rate", "1.5"],
        ["--defect-rate", "-0.01"],
        ["--defect-rate", "nan"],
        ["--unknown-rate", "-0.1"],
        ["--unknown-rate", "inf"],
        ["--out-of-control-lots", "0,3"],
        ["--out-of-control-lots", "11"],
        ["--out-of-control-lots", "a,b"],
        ["--out-of-control-lots", "3,3"],
        ["--out-of-control-lots", "3,"],
        ["--out-of-control-lots", "-3"],
        ["--out-of-control-lots", "٣"],  # non-ASCII digit
        ["--device-id", "sim-01\n"],
        ["--device-id", "SIM-01"],
        ["--device-id", "si"],
        ["--model-version", "sim-v0\n"],
        ["--model-version", "Sim-V0"],
        ["--seed", "-1"],
        ["--start", "2026-10-01T06:00:00"],
        ["--start", "yesterday"],
        ["--start", "0001-01-01T00:00:00+01:00"],  # out of range in UTC
        ["--start", "9999-12-31T23:59:00+00:00"],  # last item out of range
    ],
)
def test_invalid_arguments_exit_2(argv: list[str], run: Callable[..., Run]) -> None:
    api = FakeApi()
    result = run(["--dry-run", "--device-id", "sim-01", "--lots", "10", *argv], api)
    assert result.code == 2
    assert result.out == ""
    assert "error" in result.err
    assert api.requests == []


def test_device_id_is_required(run: Callable[..., Run]) -> None:
    assert run(["--dry-run", "--start", START]).code == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["--lots", "1"],
        ["--lots", "500", "--lot-size", "1"],
        ["--lot-size", "1000", "--lots", "1"],
        ["--lot-size-min", "1", "--lot-size-max", "1000", "--lots", "1"],
        ["--lot-size-min", "4", "--lot-size-max", "4"],
        ["--defect-rate", "0", "--unknown-rate", "1"],
        ["--defect-rate", "1", "--unknown-rate", "0"],
        ["--out-of-control-lots", " 1, 10 ", "--lots", "10"],
        ["--out-of-control-lots", ""],
        ["--seed", "0"],
        ["--model-version", "a.b-1"],
    ],
)
def test_boundary_arguments_are_accepted(argv: list[str]) -> None:
    sim.parse_args(["--dry-run", "--device-id", "sim-01", *argv], now=NOW)


def test_help_exits_0(run: Callable[..., Run]) -> None:
    result = run(["--help"])
    assert result.code == 0
    assert "SIM_DEVICE_API_KEY" in result.out


def test_start_in_the_future_is_refused(run: Callable[..., Run], online_env: str) -> None:
    api = FakeApi()
    start = (NOW + timedelta(hours=1)).isoformat()
    result = run(["--start", start], api)
    assert result.code == 2
    assert api.requests == []


def test_start_limit_is_the_last_generated_item() -> None:
    # 2 lots of 4 items: the last item is at start + 10 min + 7.5 min.
    limit = NOW + timedelta(minutes=5) - timedelta(minutes=17.5)
    argv = ["--lots", "2", "--lot-size", "4", "--start"]
    cfg = _cfg(*argv, limit.isoformat())
    assert max(item.inspected_at for item in sim.generate(cfg)) == NOW + timedelta(minutes=5)
    with pytest.raises(SystemExit) as exc:
        _cfg(*argv, (limit + timedelta(microseconds=1)).isoformat())
    assert exc.value.code == 2


def test_start_limit_uses_the_largest_random_lot_size() -> None:
    limit = NOW + timedelta(minutes=5) - timedelta(minutes=9)  # one lot, up to 10 items
    argv = ["--lots", "1", "--lot-size-min", "1", "--lot-size-max", "10", "--start"]
    _cfg(*argv, limit.isoformat())
    with pytest.raises(SystemExit):
        _cfg(*argv, (limit + timedelta(seconds=1)).isoformat())


def test_start_is_normalized_to_utc() -> None:
    cfg = _cfg("--start", "2026-10-01T01:30:00-03:00", "--lots", "1")
    assert cfg.start == datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
    assert sim.generate(cfg)[0].lot_id == "SIM-20261001-001"


def test_lot_id_uses_the_utc_date_of_start() -> None:
    items = _items("--start", "2026-09-30T22:00:00-03:00", "--lots", "1", "--lot-size", "1")
    assert items[0].lot_id == "SIM-20261001-001"


@pytest.mark.parametrize(
    "url",
    [
        "http://api.exemplo.org",
        "http://localhost.example.org",
        "ftp://api.example.test",
        "api.example.test",
        "https://",
        "https://api.example.test:99999",
        "https://api.example.test/?q=1",
        "https://api.example.test/#frag",
    ],
)
def test_invalid_api_url_exits_2(url: str, online_env: str, run: Callable[..., Run]) -> None:
    api = FakeApi()
    result = run(["--start", START, "--api-url", url], api)
    assert result.code == 2
    assert api.requests == []


def test_api_url_with_credentials_is_refused_without_echo(
    online_env: str, run: Callable[..., Run]
) -> None:
    secret = "pw" + secrets.token_hex(6)
    url = f"https://user:{secret}@api.example.test"
    result = run(["--start", START, "--api-url", url])
    assert result.code == 2
    assert secret not in result.err + result.out


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8001", "http://localhost:8001/", "https://localhost"]
)
def test_local_http_url_is_accepted(url: str, online_env: str, run: Callable[..., Run]) -> None:
    api = FakeApi()
    result = run(["--start", START, "--lots", "1", "--api-url", url], api)
    assert result.code == 0, result.err
    assert len(api.requests) == 2


def test_missing_url_exits_2(
    online_env: str, monkeypatch: pytest.MonkeyPatch, run: Callable[..., Run]
) -> None:
    monkeypatch.setenv("CLOUD_API_URL", "  ")
    api = FakeApi()
    assert run(["--start", START], api).code == 2
    assert api.requests == []


@pytest.mark.parametrize("value", [None, ""])
def test_missing_key_exits_2(
    value: str | None, online_env: str, monkeypatch: pytest.MonkeyPatch, run: Callable[..., Run]
) -> None:
    if value is None:
        monkeypatch.delenv("SIM_DEVICE_API_KEY")
    else:
        monkeypatch.setenv("SIM_DEVICE_API_KEY", value)
    api = FakeApi()
    assert run(["--start", START], api).code == 2
    assert api.requests == []


@pytest.mark.parametrize("bad", ["two words", "line\nbreak", "acentuação"])
def test_key_with_invalid_characters_exits_2_without_echo(
    bad: str, online_env: str, run: Callable[..., Run]
) -> None:
    secret = secrets.token_hex(8)
    result = run(["--start", START, "--api-key", f"{secret}{bad}"])
    assert result.code == 2
    assert secret not in result.err + result.out


def test_dry_run_needs_no_url_nor_key(run: Callable[..., Run]) -> None:
    api = FakeApi()
    result = run(_dry("--lots", "1", "--lot-size", "3"), api)
    assert result.code == 0
    assert api.requests == []


# ---------------------------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------------------------


def test_dry_run_output(run: Callable[..., Run]) -> None:
    api = FakeApi()
    result = run(_dry("--seed", "42", "--lots", "3", "--lot-size", "10"), api)
    assert result.code == 0
    lines = result.out.splitlines()
    assert len(lines) == 30
    items = [InspectionCreate.model_validate_json(line) for line in lines]
    for item, line in zip(items, lines, strict=True):
        assert set(json.loads(line)) == CONTRACT_KEYS
        assert item.source == "simulated"
        assert item.model_version == "sim-v0"
        assert item.model_sha256 == "0" * 64
        assert item.device_id == "sim-01"
    lots = Counter(item.lot_id for item in items)
    assert lots == {f"SIM-20261001-00{i}": 10 for i in (1, 2, 3)}
    times = [item.inspected_at for item in items]
    assert times == sorted(times) and len(set(times)) == 30
    assert times[0] == datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    assert times[1] - times[0] == timedelta(minutes=1)
    assert times[10] == datetime(2026, 10, 1, 6, 10, tzinfo=UTC)
    assert result.err == "sent=30 lots=3 seed=42 source=simulated\n"
    assert api.requests == []


def test_same_seed_same_output_other_seed_other_ids(run: Callable[..., Run]) -> None:
    argv = _dry("--seed", "42", "--lots", "3", "--lot-size", "10")
    first, second = run(argv).out, run(argv).out
    assert first == second
    ids_42 = [json.loads(line)["inspection_id"] for line in first.splitlines()]
    other = run(_dry("--seed", "43", "--lots", "3", "--lot-size", "10")).out
    ids_43 = [json.loads(line)["inspection_id"] for line in other.splitlines()]
    assert not set(ids_42) & set(ids_43)
    for raw in ids_42 + ids_43:
        assert uuid.UUID(raw).version == 4
    assert len(set(ids_42)) == len(ids_42) == 30


def test_ids_do_not_depend_on_start() -> None:
    a = _items("--seed", "5", "--start", START, "--lots", "2", "--lot-size", "3")
    b = _items("--seed", "5", "--start", "2026-09-01T00:00:00Z", "--lots", "2", "--lot-size", "3")
    assert [i.inspection_id for i in a] == [i.inspection_id for i in b]
    assert [i.inspected_at for i in a] != [i.inspected_at for i in b]


def test_rng_order_starts_with_the_first_id() -> None:
    rng = sim.random.Random(42)
    expected = uuid.UUID(int=rng.getrandbits(128), version=4)
    assert _items("--seed", "42", "--start", START, "--lots", "1")[0].inspection_id == expected


def test_random_lot_sizes_consume_the_rng_first() -> None:
    rng = sim.random.Random(3)
    n = rng.randint(3, 8)
    first_id = uuid.UUID(int=rng.getrandbits(128), version=4)
    items = _items("--seed", "3", "--start", START, "--lots", "1", "--lot-size-min", "3",
                   "--lot-size-max", "8")  # fmt: skip
    assert len(items) == n
    assert items[0].inspection_id == first_id


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--unknown-rate", "1"],
        ["--unknown-rate", "0", "--defect-rate", "1"],
        ["--lot-size-min", "1", "--lot-size-max", "40", "--out-of-control-lots", "2,9"],
        ["--model-version", "partqc-mnv3-v1", "--defect-rate", "0.33"],
    ],
)
def test_source_is_always_simulated(argv: list[str]) -> None:
    items = _items("--seed", "11", "--start", START, *argv)
    assert items
    assert {item.source for item in items} == {"simulated"}


def test_item_rules() -> None:
    items = _items("--seed", "7", "--start", START, "--lots", "20", "--lot-size", "100",
                   "--unknown-rate", "0.2", "--defect-rate", "0.3")  # fmt: skip
    assert len(items) == 2000
    for item in items:
        assert 40 <= item.latency_ms <= 180
        if item.object_type == ObjectType.UNKNOWN:
            assert item.grade is item.grade_score is item.grade_confidence is None
            assert 0.30 <= item.type_confidence <= 0.69
            assert item.needs_review is True
        else:
            assert item.object_type in (ObjectType.SCREW, ObjectType.NUT)
            assert 0.75 <= item.type_confidence <= 0.99
            assert 0.55 <= item.grade_confidence <= 0.95
            index = sim.grade_index(item.grade)
            assert 0.0 <= item.grade_score <= 4.0
            assert abs(item.grade_score - index) <= 0.4 + 1e-12
            assert item.needs_review == (
                item.type_confidence < 0.80 or item.grade_confidence < 0.60
            )
    assert {item.grade_score for item in items if item.grade == Grade.PERFECT} >= {0.0}
    types = Counter(item.object_type for item in items)
    assert abs(types[ObjectType.SCREW] - types[ObjectType.NUT]) < 200


def test_distribution_of_grades() -> None:
    items = _items("--seed", "1", "--start", START, "--lots", "20", "--lot-size", "500",
                   "--defect-rate", "0.2", "--unknown-rate", "0")  # fmt: skip
    defective = [i for i in items if is_defective(i.grade)]
    good = [i for i in items if not is_defective(i.grade)]
    assert abs(len(defective) / len(items) - 0.20) <= 0.02
    assert abs(sum(i.grade == Grade.POOR for i in defective) / len(defective) - 0.70) <= 0.04
    for grade, expected in ((Grade.PERFECT, 0.40), (Grade.GOOD, 0.35), (Grade.FAIR, 0.25)):
        assert abs(sum(i.grade == grade for i in good) / len(good) - expected) <= 0.03


def test_distribution_of_unknown() -> None:
    items = _items("--seed", "2", "--start", START, "--lots", "10", "--lot-size", "200",
                   "--unknown-rate", "0.1")  # fmt: skip
    unknown = [i for i in items if i.object_type == ObjectType.UNKNOWN]
    assert abs(len(unknown) / len(items) - 0.10) <= 0.03
    assert all(i.type_confidence < 0.70 for i in unknown)


def test_extreme_rates() -> None:
    none = _items("--seed", "4", "--start", START, "--defect-rate", "0", "--unknown-rate", "0")
    assert not any(is_defective(i.grade) for i in none)
    every = _items("--seed", "4", "--start", START, "--defect-rate", "1", "--unknown-rate", "0")
    assert all(is_defective(i.grade) for i in every)
    unknown = _items("--seed", "4", "--start", START, "--unknown-rate", "1")
    assert all(i.object_type == ObjectType.UNKNOWN for i in unknown)


def test_out_of_control_rate_is_three_times_capped_at_one() -> None:
    cfg = _cfg("--defect-rate", "0.5", "--lots", "4", "--out-of-control-lots", "2,4")
    assert [cfg.lot_rate(i) for i in (1, 2, 3, 4)] == [0.5, 1.0, 0.5, 1.0]
    items = sim.generate(
        _cfg(
            "--seed",
            "8",
            "--start",
            START,
            "--defect-rate",
            "0.5",
            "--unknown-rate",
            "0",
            "--lots",
            "3",
            "--out-of-control-lots",
            "2",
        )  # fmt: skip
    )
    lot_2 = [i for i in items if i.lot_id.endswith("-002")]
    assert lot_2 and all(is_defective(i.grade) for i in lot_2)


def test_random_lot_sizes_stay_in_range() -> None:
    items = _items("--seed", "3", "--start", START, "--lots", "5", "--lot-size-min", "3",
                   "--lot-size-max", "8")  # fmt: skip
    sizes = Counter(item.lot_id for item in items)
    assert len(sizes) == 5
    assert all(3 <= n <= 8 for n in sizes.values())


def test_p_chart_flags_the_out_of_control_lots() -> None:
    items = _items("--seed", "42", "--lots", "30", "--lot-size", "200", "--defect-rate", "0.1",
                   "--unknown-rate", "0", "--out-of-control-lots", "24,28")  # fmt: skip
    by_lot: dict[str, list[InspectionCreate]] = defaultdict(list)
    for item in items:
        by_lot[item.lot_id].append(item)
    lots = [
        LotCounts(
            lot_id=lot_id,
            started_at=min(i.inspected_at for i in rows),
            ended_at=max(i.inspected_at for i in rows),
            n=len(rows),
            defects=sum(is_defective(i.grade) for i in rows),
        )
        for lot_id, rows in by_lot.items()
    ]
    chart = compute_p_chart(lots, baseline_lots=20, min_lot_size=5)
    flagged = {p.lot_id[-3:] for p in chart.points if p.out_of_control}
    assert {"024", "028"} <= flagged
    assert len(flagged - {"024", "028"}) <= 2


def test_invalid_generated_item_exits_1(
    monkeypatch: pytest.MonkeyPatch, run: Callable[..., Run]
) -> None:
    monkeypatch.setattr(sim, "MODEL_SHA256", "x")
    result = run(_dry("--lots", "1", "--lot-size", "1"))
    assert result.code == 1
    assert result.out == ""
    assert "internal error" in result.err


# ---------------------------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------------------------

SEND_ARGS = ["--seed", "42", "--lots", "10", "--lot-size", "25", "--start", START]


def test_send_and_resend_are_idempotent(online_env: str, run: Callable[..., Run]) -> None:
    api = FakeApi()
    first = run(SEND_ARGS, api)
    assert first.code == 0, first.err
    assert [(r.method, r.url.path) for r in api.requests] == [
        ("GET", "/api/v1/health"),
        ("POST", "/api/v1/inspections/batch"),
        ("POST", "/api/v1/inspections/batch"),
        ("POST", "/api/v1/inspections/batch"),
    ]
    sizes = [len(json.loads(r.content)["items"]) for r in api.batch_requests]
    assert sizes == [100, 100, 50]
    assert all(r.headers["X-API-Key"] == online_env for r in api.batch_requests)
    assert "X-API-Key" not in api.requests[0].headers
    assert first.out == "sent=250 created=250 duplicate=0 lots=10 seed=42 source=simulated\n"

    second = run(SEND_ARGS, api)
    assert second.code == 0
    assert second.out == "sent=250 created=0 duplicate=250 lots=10 seed=42 source=simulated\n"
    assert len(api.store) == 250
    assert online_env not in first.out + first.err + second.out + second.err


def test_batch_items_have_exactly_the_contract_keys(
    online_env: str, run: Callable[..., Run]
) -> None:
    api = FakeApi()
    assert run(SEND_ARGS, api).code == 0
    for request in api.batch_requests:
        body = json.loads(request.content)
        assert set(body) == {"items"}
        assert all(set(item) == CONTRACT_KEYS for item in body["items"])
        assert request.headers["Content-Type"] == "application/json"


def test_timeouts(online_env: str, run: Callable[..., Run]) -> None:
    api = FakeApi()
    assert run(SEND_ARGS, api).code == 0
    health_timeout = api.requests[0].extensions["timeout"]
    batch_timeout = api.batch_requests[0].extensions["timeout"]
    assert set(health_timeout.values()) == {90.0}
    assert set(batch_timeout.values()) == {10.0}


@pytest.mark.parametrize("health", [503, 500, 404, httpx.ConnectError("down")])
def test_health_failure_exits_5(health: Script, online_env: str, run: Callable[..., Run]) -> None:
    api = FakeApi(health=health)
    result = run(SEND_ARGS, api)
    assert result.code == 5
    assert api.batch_requests == []
    assert result.sleeps == []


def test_retry_then_success(online_env: str, run: Callable[..., Run]) -> None:
    def created(request: httpx.Request) -> httpx.Response:
        response = api._ingest(request)
        return httpx.Response(201, content=response.content)

    api = FakeApi(batch_script=[503, httpx.ConnectError("reset"), created])
    result = run(SEND_ARGS, api)
    assert result.code == 0, result.err
    assert result.sleeps == [2, 4]
    assert len(api.batch_requests) == 5
    assert len(api.store) == 250
    assert "created=250 duplicate=0" in result.out


@pytest.mark.parametrize(
    "failure", [503, 500, 502, httpx.ReadTimeout("slow"), httpx.ConnectError("down")]
)
def test_retries_exhausted_exit_5(
    failure: Script, online_env: str, run: Callable[..., Run]
) -> None:
    api = FakeApi(batch_script=[failure] * 4)
    result = run(SEND_ARGS, api)
    assert result.code == 5
    assert result.sleeps == [2, 4, 8]
    assert len(api.batch_requests) == 4
    assert api.store == {}
    assert "seed=42" in result.err


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_exits_3_without_more_requests(
    status: int, online_env: str, run: Callable[..., Run]
) -> None:
    api = FakeApi(batch_script=[status])
    result = run(SEND_ARGS, api)
    assert result.code == 3
    assert len(api.batch_requests) == 1
    assert result.sleeps == []
    assert online_env not in result.out + result.err


def test_key_from_the_command_line_is_not_echoed(
    online_env: str, monkeypatch: pytest.MonkeyPatch, run: Callable[..., Run]
) -> None:
    monkeypatch.delenv("SIM_DEVICE_API_KEY")
    key = "cli-" + secrets.token_urlsafe(16)
    api = FakeApi(batch_script=[401])
    result = run([*SEND_ARGS, "--api-key", key], api)
    assert result.code == 3
    assert api.batch_requests[0].headers["X-API-Key"] == key
    assert key not in result.out + result.err


@pytest.mark.parametrize(
    ("detail", "expected"),
    [("x", "x"), ([{"loc": ["body"], "msg": "bad"}], '[{"loc":["body"],"msg":"bad"}]')],
)
def test_422_exits_4_with_detail(
    detail: Any, expected: str, online_env: str, run: Callable[..., Run]
) -> None:
    api = FakeApi(batch_script=[lambda _r: httpx.Response(422, json={"detail": detail})])
    result = run(SEND_ARGS, api)
    assert result.code == 4
    assert expected in result.err
    assert len(api.batch_requests) == 1
    assert result.sleeps == []


def test_422_without_json_body(online_env: str, run: Callable[..., Run]) -> None:
    api = FakeApi(batch_script=[lambda _r: httpx.Response(422, text="nope")])
    result = run(SEND_ARGS, api)
    assert result.code == 4
    assert "(no detail)" in result.err


@pytest.mark.parametrize("status", [400, 404, 413, 429, 302])
def test_other_status_exits_5_without_retry(
    status: int, online_env: str, run: Callable[..., Run]
) -> None:
    api = FakeApi(batch_script=[status])
    result = run(SEND_ARGS, api)
    assert result.code == 5
    assert len(api.batch_requests) == 1
    assert result.sleeps == []


@pytest.mark.parametrize(
    "body", [b"not json", b'{"results": []}', b'{"results": [{"status": "created"}]}']
)
def test_unexpected_success_body_exits_5(
    body: bytes, online_env: str, run: Callable[..., Run]
) -> None:
    api = FakeApi(batch_script=[lambda _r: httpx.Response(200, content=body)])
    assert run(SEND_ARGS, api).code == 5


def test_failure_on_a_later_batch_reports_progress(
    online_env: str, run: Callable[..., Run]
) -> None:
    api = FakeApi(batch_script=[200, 403])
    result = run(SEND_ARGS, api)
    assert result.code == 3
    assert len(api.batch_requests) == 2
    assert "sent=100 created=100 duplicate=0 seed=42" in result.err
    assert result.out == ""


def test_send_returns_the_summary(online_env: str) -> None:
    cfg = sim.parse_args(["--start", START, "--lots", "2", "--lot-size", "3"], now=NOW)
    api = FakeApi()
    summary = sim.send(sim.generate(cfg), cfg, transport=api.transport(), sleep=lambda _s: None)
    assert summary == sim.SendSummary(sent=6, created=6, duplicate=0)


def test_send_refuses_a_dry_run_config() -> None:
    with pytest.raises(ValueError, match="dry-run"):
        sim.send([], _cfg(), transport=FakeApi().transport())


# ---------------------------------------------------------------------------------------------
# Real qc_api app in process (database)
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def app_transport(clean_db: str, key: str) -> Iterator[httpx.MockTransport]:
    """The real API (``create_app``) behind a ``MockTransport``; ``sim-01`` owns ``key``."""
    from qc_api.main import create_app

    with psycopg.connect(clean_db, autocommit=True, prepare_threshold=None) as conn:
        conn.execute(
            "insert into devices (device_id, api_key_hash) values (%s, %s)",
            ("sim-01", hash_api_key(key)),
        )
    settings = Settings(DATABASE_URL=clean_db, READ_API_KEY=secrets.token_urlsafe(32))
    with TestClient(create_app(settings)) as client:

        def forward(request: httpx.Request) -> httpx.Response:
            headers = {
                k: v for k, v in request.headers.items() if k in {"x-api-key", "content-type"}
            }
            response = client.request(
                request.method, request.url.path, content=request.content, headers=headers
            )
            return httpx.Response(response.status_code, content=response.content)

        yield httpx.MockTransport(forward)


def _count(conninfo: str) -> list[tuple[str, int]]:
    with psycopg.connect(conninfo, autocommit=True, prepare_threshold=None) as conn:
        query = "select source, count(*) from inspections group by source"
        return [(row[0], row[1]) for row in conn.execute(query).fetchall()]


@pytest.mark.db
def test_real_api_is_idempotent(
    app_transport: httpx.MockTransport,
    clean_db: str,
    online_env: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = [*SEND_ARGS, "--api-url", "http://127.0.0.1:8001"]
    assert sim.main(argv, transport=app_transport, sleep=lambda _s: None, now=NOW) == 0
    assert "sent=250 created=250 duplicate=0" in capsys.readouterr().out
    assert sim.main(argv, transport=app_transport, sleep=lambda _s: None, now=NOW) == 0
    assert "sent=250 created=0 duplicate=250" in capsys.readouterr().out
    assert _count(clean_db) == [("simulated", 250)]


@pytest.mark.db
def test_real_api_refuses_another_device(
    app_transport: httpx.MockTransport,
    clean_db: str,
    online_env: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = [*SEND_ARGS, "--device-id", "sim-02"]
    assert sim.main(argv, transport=app_transport, sleep=lambda _s: None, now=NOW) == 3
    assert online_env not in "".join(capsys.readouterr())
    assert _count(clean_db) == []
