"""Acceptance tests for SPEC-027 section 4.3 (``scripts/simulate.py``: usage errors, URL, lots).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test per CA (``test_caNN_*``, CA-07 to CA-11); ``test_extra_*`` tests are
exploratory edge cases around SPEC-027 section 4.3.

As in SPEC-014, the script is loaded with ``importlib.util.spec_from_file_location`` and driven
through ``main([...], transport=MockTransport(...), sleep=<recorder>, now=<fixed>)``. No real
network. Every secret-like value (``S`` of CA-07, the device keys) is generated at run time.

Common precondition: ``SIM_DEVICE_ID=sim-01`` is set in the environment (the device id is
checked before the other options, so without it the CA-07 cases ``--start``,
``--out-of-control-lots`` and ``--model-version`` would report the missing device id instead of
their own option; noted in ``reviews/SPEC-027/r1-dev-report.md``). The other two simulator
variables are removed.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import httpx
import pytest

import qc_contracts

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "simulate.py"
README = ROOT / "README.md"

API_URL = "https://api.partqc.test"
URL_HEALTH = "/api/v1/health"
URL_BATCH = "/api/v1/inspections/batch"
NOW = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)
START = "2026-10-01T10:00:00Z"
INVALID_URL = "invalid --api-url (not shown)"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("simulate_spec027_acceptance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sim = _load_script()


# --------------------------------------------------------------------------- fake API


class FakeApi:
    """Fake cloud API: health 200, batch answers ``created`` for every item."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.requests: list[httpx.Request] = []

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def batches(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "POST" and r.url.path == URL_BATCH]

    def handler(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if request.method == "GET" and request.url.path == URL_HEALTH:
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "db": "ok",
                    "api_version": "0.1.0",
                    "contract_version": qc_contracts.__version__,
                },
            )
        if request.method == "POST" and request.url.path == URL_BATCH:
            if request.headers.get("X-API-Key") != self.key:
                return httpx.Response(401, json={"detail": "Missing or invalid API key"})
            items = json.loads(request.content)["items"]
            results = [{"inspection_id": i["inspection_id"], "status": "created"} for i in items]
            return httpx.Response(200, json={"results": results})
        return httpx.Response(404, json={"detail": "Not Found"})


def _refuse_all(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
    raise AssertionError(f"unexpected request: {request.method} {request.url}")


# --------------------------------------------------------------------------- running


@dataclass
class Run:
    code: int
    out: str
    err: str
    log: str
    sleeps: list[float] = field(default_factory=list)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CLOUD_API_URL", "SIM_DEVICE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIM_DEVICE_ID", "sim-01")
    monkeypatch.setenv("COLUMNS", "80")


@pytest.fixture
def run(capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> Callable[..., Run]:
    def _run(argv: list[str], *, api: FakeApi | None = None, now: datetime = NOW) -> Run:
        caplog.set_level(logging.DEBUG)
        caplog.clear()
        sleeps: list[float] = []
        transport = api.transport if api is not None else httpx.MockTransport(_refuse_all)
        capsys.readouterr()
        try:
            code = sim.main(argv, transport=transport, sleep=sleeps.append, now=now)
        except SystemExit as exc:  # pragma: no cover - --help may also exit
            code = exc.code if isinstance(exc.code, int) else -1
        out, err = capsys.readouterr()
        log = caplog.text + "\n".join(f"{r.getMessage()} {r.args!r}" for r in caplog.records)
        return Run(code, out, err, log, sleeps)

    return _run


def new_secret() -> str:
    """``S`` of CA-07: starts with a letter, so argparse never reads it as an option."""
    return "Z" + secrets.token_urlsafe(32)


def new_key() -> str:
    return "k" + secrets.token_urlsafe(24)


def dash_key() -> str:
    """A device key that starts with ``-`` (SEC-02)."""
    return "-" + secrets.token_urlsafe(32)


def send_argv(url: str, key: str, *extra: str) -> list[str]:
    return [
        "--api-url",
        url,
        "--api-key",
        key,
        "--device-id",
        "sim-01",
        "--seed",
        "1",
        "--lots",
        "1",
        "--lot-size",
        "5",
        "--start",
        START,
        *extra,
    ]


def ca07_cases(s: str) -> list[tuple[list[str], str]]:
    """``(argv, text the stderr must contain)`` of CA-07."""
    unrec = "unrecognized arguments"
    return [
        (["--api-keyy", s], unrec),
        (["--api-keyy=" + s], unrec),
        ([s], unrec),
        (["--lots", s], "--lots"),
        (["--lot-size", s], "--lot-size"),
        (["--seed", "x" + s], "--seed"),
        (["--defect-rate", s], "--defect-rate"),
        (["--unknown-rate", s], "--unknown-rate"),
        (["--start", s], "--start"),
        (["--out-of-control-lots", s], "--out-of-control-lots"),
        (["--device-id", s], "--device-id"),
        (["--model-version", s + "!"], "--model-version"),
    ]


CA07_IDS = [
    "api-keyy-space",
    "api-keyy-equals",
    "loose-value",
    "lots",
    "lot-size",
    "seed",
    "defect-rate",
    "unknown-rate",
    "start",
    "out-of-control-lots",
    "device-id",
    "model-version",
]

CA09_URLS = [
    "http://local\nhost:8001",
    "https://exa\x01mple.com",
    "https://example.com/\t",
    "https://exa mple.com",
    "https://exämple.com",
    "https://example.com\x7f",
    "https://example.com\x1b[31m",
]
CA09_IDS = ["newline", "soh", "tab", "space", "non-ascii", "del", "ansi-escape"]

CA10_LISTS = ["1" * 5000, "12345"]

# CA-08 of SPEC-014: extra arguments after ``--dry-run --seed 1 --lots 10 --device-id sim-01``.
SPEC014_CA08 = [
    ["--out-of-control-lots", "0,3"],
    ["--out-of-control-lots", "11"],
    ["--out-of-control-lots", "a,b"],
    ["--out-of-control-lots", "3,3"],
    ["--defect-rate", "1.5"],
    ["--unknown-rate", "-0.1"],
    ["--device-id", "sim-01\n"],
    ["--model-version", "sim-v0\n"],
]


def assert_clean_usage_error(result: Run, *forbidden: str) -> None:
    assert result.code == 2, (result.code, result.err)
    assert "Traceback" not in result.err
    assert "Traceback" not in result.out
    for text in forbidden:
        assert text not in result.out, text
        assert text not in result.err, text
        assert text not in result.log, text


# --------------------------------------------------------------------------- CA-07


@pytest.mark.parametrize("index", range(12), ids=CA07_IDS)
def test_ca07_usage_errors_never_echo_the_value(run: Callable[..., Run], index: int) -> None:
    s = new_secret()
    argv, must_contain = ca07_cases(s)[index]

    result = run(["--dry-run", *argv])

    assert_clean_usage_error(result, s)
    assert must_contain in result.err, result.err


def test_ca07_help_exits_0_with_usage(run: Callable[..., Run]) -> None:
    result = run(["--help"])
    assert result.code == 0, result.err
    assert "usage:" in result.out


# --------------------------------------------------------------------------- CA-08


def test_ca08_readme_and_help_document_the_equals_form(run: Callable[..., Run]) -> None:
    assert "--api-key=" in README.read_text(encoding="utf-8")
    result = run(["--help"])
    assert result.code == 0
    assert "--api-key=" in result.out


@pytest.mark.parametrize("columns", ["40", "60", "80", "200"])
def test_ca08_help_keeps_the_equals_form_at_any_width(
    run: Callable[..., Run], monkeypatch: pytest.MonkeyPatch, columns: str
) -> None:
    monkeypatch.setenv("COLUMNS", columns)
    result = run(["--help"])
    assert result.code == 0
    assert "--api-key=" in result.out


def test_ca08_key_starting_with_dash_in_the_equals_form(run: Callable[..., Run]) -> None:
    key = dash_key()
    api = FakeApi(key)
    argv = send_argv(API_URL, "placeholder")
    argv[argv.index("--api-key") : argv.index("--api-key") + 2] = [f"--api-key={key}"]

    result = run(argv, api=api)

    assert result.code == 0, result.err
    assert api.batches(), "no batch was sent"
    assert all(r.headers.get("X-API-Key") == key for r in api.batches())
    assert key not in result.out + result.err + result.log


def test_ca08_key_starting_with_dash_in_the_environment(
    run: Callable[..., Run], monkeypatch: pytest.MonkeyPatch
) -> None:
    key = dash_key()
    monkeypatch.setenv("SIM_DEVICE_API_KEY", key)
    api = FakeApi(key)
    argv = send_argv(API_URL, "placeholder")
    del argv[argv.index("--api-key") : argv.index("--api-key") + 2]

    result = run(argv, api=api)

    assert result.code == 0, result.err
    assert api.batches(), "no batch was sent"
    assert all(r.headers.get("X-API-Key") == key for r in api.batches())
    assert key not in result.out + result.err + result.log


# --------------------------------------------------------------------------- CA-09


@pytest.mark.parametrize("url", CA09_URLS, ids=CA09_IDS)
def test_ca09_api_url_outside_visible_ascii_is_refused(run: Callable[..., Run], url: str) -> None:
    key = new_key()
    api = FakeApi(key)

    result = run(send_argv(url, key), api=api)

    assert result.code == 2, result.err
    assert api.requests == []
    assert INVALID_URL in result.err
    for text in ("Traceback", "mple.com", "host:8001"):
        assert text not in result.err, (text, result.err)
    assert key not in result.out + result.err


@pytest.mark.parametrize("url", ["https://api.example.org", "http://127.0.0.1:8001"])
def test_ca09_visible_ascii_url_still_sends(run: Callable[..., Run], url: str) -> None:
    key = new_key()
    api = FakeApi(key)

    result = run(send_argv(url, key), api=api)

    assert result.code == 0, result.err
    assert api.batches()
    expected = httpx.URL(url)
    assert {(r.url.host, r.url.port) for r in api.requests} == {(expected.host, expected.port)}


# --------------------------------------------------------------------------- CA-10


@pytest.mark.parametrize("lots", CA10_LISTS, ids=["5000-ones", "five-digits"])
def test_ca10_lot_numbers_with_more_than_4_digits_exit_2(
    run: Callable[..., Run], lots: str
) -> None:
    result = run(["--dry-run", "--lots", "10", "--out-of-control-lots", lots])
    assert result.code == 2, result.err
    assert "Traceback" not in result.err
    assert result.out == ""


def test_ca10_leading_zeros_give_the_same_bytes(run: Callable[..., Run]) -> None:
    base = ["--dry-run", "--lots", "10", "--seed", "42", "--start", START]
    padded = run([*base, "--out-of-control-lots", "3,0007"])
    plain = run([*base, "--out-of-control-lots", "3,7"])

    assert padded.code == plain.code == 0, (padded.err, plain.err)
    assert padded.out.encode() == plain.out.encode()
    assert len(padded.out.splitlines()) > 0


# --------------------------------------------------------------------------- CA-11


def ca11_argvs() -> list[list[str]]:
    s = new_secret()
    key = new_key()
    argvs: list[list[str]] = []
    for extra in SPEC014_CA08:
        argvs.append(["--dry-run", "--seed", "1", "--lots", "10", "--device-id", "sim-01", *extra])
        argvs.append(send_argv(API_URL, key, "--lots", "10", *extra))
    argvs += [["--dry-run", *argv] for argv, _ in ca07_cases(s)]
    argvs += [send_argv(url, key) for url in CA09_URLS]
    argvs += [["--dry-run", "--lots", "10", "--out-of-control-lots", lots] for lots in CA10_LISTS]
    return argvs


def test_ca11_no_invalid_usage_exits_with_code_1(run: Callable[..., Run]) -> None:
    argvs = ca11_argvs()
    assert len(argvs) == 16 + 12 + 7 + 2
    codes: list[tuple[int, list[str]]] = []
    for argv in argvs:
        key = new_key()
        result = run(argv, api=FakeApi(key))
        codes.append((result.code, argv))
        assert "Traceback" not in result.err, argv
    assert [c for c, _ in codes if c == 1] == [], [a for c, a in codes if c == 1]
    assert all(c == 2 for c, _ in codes), [(c, a) for c, a in codes if c != 2]


# --------------------------------------------------------------------------- extras


@pytest.mark.parametrize(
    "argv_of",
    [
        lambda s: ["--lots=" + s],
        lambda s: ["--lot-size-min", s],
        lambda s: ["--lot-size-max", s],
        lambda s: ["--dry-run=" + s],
        lambda s: [s + " with spaces", "and more"],
        lambda s: ["--lots", s + "'"],
        lambda s: ["--lots", s + "\"'\\"],
        lambda s: ["--lots", "é" + s + "ção"],
        lambda s: ["--lots", s * 50],
        lambda s: ["--seed", s + "\n" + s],
        lambda s: ["--defect-rate=" + s],
        lambda s: ["--api-key", "-" + s],
        lambda s: ["--api-url", s, "--api-key"],
        lambda s: ["--", s],
    ],
    ids=[
        "lots-equals",
        "lot-size-min",
        "lot-size-max",
        "flag-with-value",
        "loose-values-with-spaces",
        "single-quote",
        "both-quotes-and-backslash",
        "unicode",
        "very-long",
        "newline-inside",
        "defect-rate-equals",
        "dash-key-after-space",
        "missing-value-at-end",
        "after-double-dash",
    ],
)
def test_extra_more_usage_errors_never_echo(
    run: Callable[..., Run], argv_of: Callable[[str], list[str]]
) -> None:
    s = new_secret()
    result = run(["--dry-run", *argv_of(s)])
    assert_clean_usage_error(result, s)


@pytest.mark.parametrize(
    "argv_of",
    [
        lambda s: ["--api=" + s],
        lambda s: ["--lot=" + s],
        lambda s: ["--api", s],
        lambda s: ["--lot-size-m=" + s],
    ],
    ids=["api-equals", "lot-equals", "api-space", "lot-size-m-equals"],
)
def test_extra_ambiguous_abbreviations_never_echo(
    run: Callable[..., Run], argv_of: Callable[[str], list[str]]
) -> None:
    """Exploratory: argparse's 'ambiguous option: <arg> could match ...' quotes the raw token."""
    s = new_secret()
    result = run(["--dry-run", *argv_of(s)])
    assert_clean_usage_error(result, s)


@pytest.mark.parametrize(
    "argv_of",
    [
        lambda s: ["--lots", "1" * 5000],
        lambda s: ["--lot-size", "9" * 5000],
        lambda s: ["--seed", "1" * 5000],
        lambda s: ["--lot-size-min", "1" * 4400, "--lot-size-max", "2"],
        lambda s: ["--defect-rate", "nan"],
        lambda s: ["--defect-rate", "inf"],
        lambda s: ["--unknown-rate", "1e400"],
        lambda s: ["--unknown-rate", "-0.0000001"],
        lambda s: ["--lots", "0"],
        lambda s: ["--lots", "501"],
        lambda s: ["--seed", "-1"],
    ],
    ids=[
        "lots-5000-digits",
        "lot-size-5000-digits",
        "seed-5000-digits",
        "lot-size-min-4400-digits",
        "defect-rate-nan",
        "defect-rate-inf",
        "unknown-rate-overflow",
        "unknown-rate-tiny-negative",
        "lots-0",
        "lots-501",
        "seed-negative",
    ],
)
def test_extra_other_numeric_limits_exit_2(
    run: Callable[..., Run], argv_of: Callable[[str], list[str]]
) -> None:
    s = new_secret()
    result = run(["--dry-run", *argv_of(s)])
    assert_clean_usage_error(result, s)
    assert result.out == ""


def test_extra_help_with_a_glued_value_shows_help_without_echo(run: Callable[..., Run]) -> None:
    """``-h<value>``: argparse shows the help (code 0); the value is never echoed."""
    s = new_secret()
    result = run(["--dry-run", "-h" + s])
    assert result.code in (0, 2)
    assert s not in result.out + result.err + result.log
    assert "Traceback" not in result.err


def test_extra_seed_with_4000_digits_is_not_a_crash(run: Callable[..., Run]) -> None:
    """Exploratory: a huge but parseable seed gives 0 or 2, never 1 nor a traceback."""
    result = run(["--dry-run", "--lots", "1", "--lot-size", "2", "--seed", "9" * 4000])
    assert result.code in (0, 2), result.err
    assert "Traceback" not in result.err


def test_extra_unrecognized_count_is_exact(run: Callable[..., Run]) -> None:
    s = new_secret()
    result = run(["--dry-run", "--api-keyy", s, s + " x y", "--bogus"])
    assert_clean_usage_error(result, s)
    assert "unrecognized arguments: 4 value(s) (not shown)" in result.err, result.err


def test_extra_invalid_int_message_format(run: Callable[..., Run]) -> None:
    s = new_secret()
    result = run(["--dry-run", "--lots", s])
    assert_clean_usage_error(result, s)
    assert "argument --lots: invalid int value (not shown)" in result.err, result.err
    assert "usage:" in result.err


@pytest.mark.parametrize(
    "url_of",
    [
        lambda s: "https://exa\x01" + s + ".com",
        lambda s: "https://" + s + ".com\n",
        lambda s: " https://" + s + ".com",
        lambda s: "https://" + s + ".com/é",
        lambda s: "https://" + s + ".com/​",
        lambda s: "https://" + s + ".com/\x00",
    ],
    ids=["soh", "trailing-newline", "leading-space", "non-ascii-path", "zero-width", "nul"],
)
def test_extra_invalid_url_never_echoed(
    run: Callable[..., Run], url_of: Callable[[str], str]
) -> None:
    s = new_secret().lower().replace("_", "a")
    key = new_key()
    api = FakeApi(key)
    result = run(send_argv(url_of(s), key), api=api)
    assert_clean_usage_error(result, s)
    assert INVALID_URL in result.err
    assert api.requests == []


@pytest.mark.parametrize(
    "url", ["https://exa\x01mple.com", "https://example.com\n", "https://exämple.com"]
)
def test_extra_cloud_api_url_env_is_checked_too(
    run: Callable[..., Run], monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    key = new_key()
    api = FakeApi(key)
    monkeypatch.setenv("CLOUD_API_URL", url)
    argv = send_argv("placeholder", key)
    del argv[argv.index("--api-url") : argv.index("--api-url") + 2]
    result = run(argv, api=api)
    assert_clean_usage_error(result, "mple.com")
    assert INVALID_URL in result.err
    assert api.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "https://xn--zz.com",
        "https://-bad-.example.org",
        "https://exa..mple.com",
        "https://[::1",
        "https://[zz]/",
        "https://example.com:99999",
        "https://example.com:-1",
        "https://example.com:",
        "https://" + "a" * 64 + ".com",
        "https://" + "a." * 200 + "com",
        "https://.example.com",
    ],
)
def test_extra_ascii_urls_that_httpx_rejects_exit_2(run: Callable[..., Run], url: str) -> None:
    """Exploratory: visible-ASCII URLs that the HTTP client cannot use give code 2, not 1."""
    key = new_key()
    api = FakeApi(key)
    result = run(send_argv(url, key), api=api)
    assert result.code in (0, 2), (result.code, result.err)
    assert result.code != 1
    assert "Traceback" not in result.err


@pytest.mark.parametrize(
    "lots",
    ["0000", "00000", "1,99999", "３", "٣", "1,,2", "+7", "-7", "1_0", "7 7"],
    ids=[
        "zero-4-digits",
        "zero-5-digits",
        "second-too-long",
        "fullwidth-digit",
        "arabic-digit",
        "empty-item",
        "trailing-space",
        "plus",
        "minus",
        "underscore",
    ],
)
def test_extra_more_bad_lot_lists_exit_2(run: Callable[..., Run], lots: str) -> None:
    result = run(["--dry-run", "--lots", "10", "--out-of-control-lots", lots])
    assert result.code == 2, (lots, result.err)
    assert "Traceback" not in result.err
    assert result.out == ""


def test_extra_spaces_around_items_are_still_ignored(run: Callable[..., Run]) -> None:
    """Inherited from SPEC-014 (same on ``main``): spaces around each item are ignored."""
    base = ["--dry-run", "--lots", "10", "--seed", "5", "--start", START]
    spaced = run([*base, "--out-of-control-lots", " 3, 0007 "])
    plain = run([*base, "--out-of-control-lots", "3,7"])
    assert spaced.code == plain.code == 0, (spaced.err, plain.err)
    assert spaced.out == plain.out


def test_extra_four_digit_lot_number_within_lots_is_accepted(run: Callable[..., Run]) -> None:
    padded = run(
        ["--dry-run", "--lots", "10", "--lot-size", "1", "--start", START]
        + ["--out-of-control-lots", "0010", "--seed", "3"]
    )
    plain = run(
        ["--dry-run", "--lots", "10", "--lot-size", "1", "--start", START]
        + ["--out-of-control-lots", "10", "--seed", "3"]
    )
    assert padded.code == plain.code == 0, (padded.err, plain.err)
    assert padded.out == plain.out


def test_extra_help_recommends_the_environment_variable(run: Callable[..., Run]) -> None:
    result = run(["--help"])
    assert result.code == 0
    assert "SIM_DEVICE_API_KEY" in result.out
    readme = README.read_text(encoding="utf-8")
    assert "SIM_DEVICE_API_KEY" in readme


def _section(text: str, title: str) -> str:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("#") and title in line)
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].startswith("#") and len(lines[i]) - len(lines[i].lstrip("#")) <= level
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_extra_readme_simulator_section_has_the_advice() -> None:
    section = _section(README.read_text(encoding="utf-8"), "Simulador")
    assert "--api-key=" in section
    assert "SIM_DEVICE_API_KEY" in section


def test_extra_summary_never_shows_the_key(run: Callable[..., Run]) -> None:
    key = dash_key()
    api = FakeApi(key)
    argv = send_argv(API_URL, "placeholder")
    argv[argv.index("--api-key") : argv.index("--api-key") + 2] = [f"--api-key={key}"]
    result = run(argv, api=api)
    assert result.code == 0, result.err
    assert key not in result.out + result.err + result.log
    assert key[1:] not in result.out + result.err + result.log
