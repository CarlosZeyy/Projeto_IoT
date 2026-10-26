"""Smoke test of the published PartQC cloud: API and dashboard (SPEC-015 section 4.5).

Usage::

    uv run --env-file <file> --package qc-api python scripts/smoke_test.py
                                                     [--api-url URL] [--dashboard-url URL]

The URLs default to ``CLOUD_API_URL`` and ``DASHBOARD_URL`` (in production both are
``https://<subdominio>``); ``http://`` is accepted only for ``localhost`` and ``127.0.0.1``.
The keys come only from the environment: ``READ_API_KEY``, ``SIM_DEVICE_ID`` and
``SIM_DEVICE_API_KEY``. TLS is always verified (the ``httpx`` default).

Eight checks run in order, each printing ``PASS <name>`` or ``FAIL <name>: <reason>``. The
reason is only an HTTP status, an exception class or the name of a diverging field: never a
key, a URL or a host name (R-03, R-13: the output is pasted into the dev-report).

The ``write`` check sends one inspection with ``source=simulated`` (R-06) in the lot
``SMOKE-<AAAAMMDDTHHMMSSZ>``.

Exit codes: ``0`` every check passed; ``1`` some check failed; ``2`` invalid usage (missing
variable or invalid URL), before any request.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn
from urllib.parse import urlsplit

import httpx

import qc_contracts
from qc_contracts import DEVICE_ID_PATTERN, Grade, InspectionCreate, ObjectType, Source

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

HEALTH_PATH = "/api/v1/health"
INSPECTIONS_PATH = "/api/v1/inspections"
DASHBOARD_HEALTH_PATH = "_stcore/health"
API_KEY_HEADER = "X-API-Key"
FOREIGN_ORIGIN = "https://example.org"

HEALTH_TIMEOUT_S = 90.0  # covers the cold start of the Render standby (section 4.1)
API_TIMEOUT_S = 30.0
DASHBOARD_TIMEOUT_S = 60.0

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})
MODEL_VERSION = "smoke-v0"
MODEL_SHA256 = "0" * 64

CHECK_NAMES: tuple[str, ...] = (
    "health",
    "write_requires_key",
    "write",
    "read_requires_key",
    "read",
    "cors_closed",
    "dashboard",
    "dashboard_health",
)


NOT_SHOWN = "(not shown)"
_UNRECOGNIZED = "unrecognized arguments: "
_UNRECOGNIZED_REDACTED = re.compile(r"unrecognized arguments: \d+ value\(s\) \(not shown\)")
# A value argparse quotes with %r (single or double quoted, with backslash escapes), with the
# ": " or the space that precedes it. Same rule as scripts/simulate.py (SPEC-027).
_QUOTED_VALUE = re.compile(r"""(?::\s*|\s+)?(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")""")


def redact_usage_error(message: str) -> str:
    """``message`` of an argparse usage error without any value typed by the operator."""
    if message.startswith(_UNRECOGNIZED):
        if _UNRECOGNIZED_REDACTED.fullmatch(message):
            return message  # already redacted by NoEchoArgumentParser.parse_args
        count = len(message[len(_UNRECOGNIZED) :].split())
        return f"{_UNRECOGNIZED}{count} value(s) {NOT_SHOWN}"
    return _QUOTED_VALUE.sub(f" {NOT_SHOWN}", message)


class NoEchoArgumentParser(argparse.ArgumentParser):
    """``ArgumentParser`` whose usage errors never repeat a typed value (RV-02 of SPEC-015 r1).

    A mistyped option can carry a key (``--api-key=<key>``), and argparse would print it on
    stderr. The usage line and the exit code 2 stay as in ``ArgumentParser``; same pattern as
    ``NoEchoArgumentParser`` of ``scripts/simulate.py``.
    """

    def parse_args(  # type: ignore[override]
        self, args: Sequence[str] | None = None, namespace: argparse.Namespace | None = None
    ) -> argparse.Namespace:
        parsed, extras = self.parse_known_args(args, namespace)
        if extras:
            self.error(f"{_UNRECOGNIZED}{len(extras)} value(s) {NOT_SHOWN}")
        return parsed

    def error(self, message: str) -> NoReturn:
        super().error(redact_usage_error(message))


class UsageError(Exception):
    """Invalid usage. The message names options or variables only, never their values."""


class CheckFailed(Exception):
    """A check failed; the message is the reason printed after ``FAIL <name>:``."""


@dataclass(frozen=True)
class Config:
    api_url: str
    dashboard_url: str
    read_api_key: str
    device_id: str
    device_api_key: str


def _visible_ascii(value: str) -> bool:
    return bool(value) and all("!" <= ch <= "~" for ch in value)


def _base_url(raw: str | None, option: str, variable: str) -> str:
    url = (raw if raw is not None else os.environ.get(variable, "")).strip()
    if not url:
        raise UsageError(f"no URL: set {variable} or pass {option}")
    if not _visible_ascii(url):
        raise UsageError(f"invalid {option} (not shown)")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        has_userinfo = parts.username is not None or parts.password is not None
        _ = parts.port  # ValueError for an invalid port
        _ = httpx.URL(url).host
    except (ValueError, httpx.InvalidURL):
        raise UsageError(f"invalid {option} (not shown)") from None
    if not host or has_userinfo or parts.query or parts.fragment:
        raise UsageError(f"invalid {option} (not shown): expected scheme://host[:port][/path]")
    if not (parts.scheme == "https" or (parts.scheme == "http" and host in LOCAL_HOSTS)):
        raise UsageError(f"{option} must use https:// (http:// only for localhost or 127.0.0.1)")
    return url.rstrip("/")


def _secret_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise UsageError(f"missing environment variable {name}")
    if not _visible_ascii(value):
        raise UsageError(f"invalid {name} (not shown): expected visible ASCII characters only")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = NoEchoArgumentParser(
        prog="smoke_test.py",
        description="Smoke test of the published PartQC API and dashboard (SPEC-015).",
        # No prefix matching (SPEC-032 section 4.1): "--api", "--dash" or "--=<value>" are
        # unknown arguments, counted and never echoed, as in scripts/simulate.py.
        allow_abbrev=False,
    )
    parser.add_argument("--api-url", help="API base URL (default: CLOUD_API_URL)")
    parser.add_argument("--dashboard-url", help="dashboard URL (default: DASHBOARD_URL)")
    return parser


def _config(args: argparse.Namespace) -> Config:
    api_url = _base_url(args.api_url, "--api-url", "CLOUD_API_URL")
    dashboard_url = _base_url(args.dashboard_url, "--dashboard-url", "DASHBOARD_URL")
    read_api_key = _secret_env("READ_API_KEY")
    device_id = _secret_env("SIM_DEVICE_ID")
    if re.fullmatch(DEVICE_ID_PATTERN, device_id) is None:
        raise UsageError(f"invalid SIM_DEVICE_ID (not shown): expected {DEVICE_ID_PATTERN}")
    device_api_key = _secret_env("SIM_DEVICE_API_KEY")
    return Config(api_url, dashboard_url, read_api_key, device_id, device_api_key)


def _inspection(device_id: str, lot_id: str) -> dict[str, object]:
    item = InspectionCreate(
        inspection_id=uuid.uuid4(),
        device_id=device_id,
        lot_id=lot_id,
        inspected_at=datetime.now(UTC),
        object_type=ObjectType.SCREW,
        grade=Grade.GOOD,
        grade_score=1.0,
        type_confidence=0.99,
        grade_confidence=0.9,
        needs_review=False,
        model_version=MODEL_VERSION,
        model_sha256=MODEL_SHA256,
        latency_ms=1,
        source=Source.SIMULATED,  # always simulated (R-06)
    )
    return item.model_dump(mode="json")


def _expect_status(response: httpx.Response, expected: int) -> None:
    if response.status_code != expected:
        raise CheckFailed(f"HTTP {response.status_code}")


def _json_object(response: httpx.Response) -> dict[str, object]:
    try:
        body = response.json()
    except ValueError:
        raise CheckFailed("body is not JSON") from None
    if not isinstance(body, dict):
        raise CheckFailed("body is not a JSON object")
    return body


class _Smoke:
    """The eight checks of section 4.5, sharing one client and the written inspection."""

    def __init__(self, cfg: Config, client: httpx.Client) -> None:
        self.cfg = cfg
        self.client = client
        self.lot_id = "SMOKE-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.written_id: str | None = None

    def _api(self, path: str) -> str:
        return self.cfg.api_url + path

    def health(self) -> None:
        response = self.client.get(self._api(HEALTH_PATH), timeout=HEALTH_TIMEOUT_S)
        _expect_status(response, 200)
        body = _json_object(response)
        expected = {
            "status": "ok",
            "db": "ok",
            "contract_version": qc_contracts.__version__,
        }
        for name, value in expected.items():
            if body.get(name) != value:
                raise CheckFailed(f"field {name}")

    def write_requires_key(self) -> None:
        response = self.client.post(
            self._api(INSPECTIONS_PATH),
            json=_inspection(self.cfg.device_id, self.lot_id),
            timeout=API_TIMEOUT_S,
        )
        _expect_status(response, 401)

    def write(self) -> None:
        payload = _inspection(self.cfg.device_id, self.lot_id)
        response = self.client.post(
            self._api(INSPECTIONS_PATH),
            json=payload,
            headers={API_KEY_HEADER: self.cfg.device_api_key},
            timeout=API_TIMEOUT_S,
        )
        _expect_status(response, 201)
        body = _json_object(response)
        if body.get("status") != "created":
            raise CheckFailed("field status")
        if body.get("inspection_id") != payload["inspection_id"]:
            raise CheckFailed("field inspection_id")
        self.written_id = str(payload["inspection_id"])

    def read_requires_key(self) -> None:
        response = self.client.get(self._api(INSPECTIONS_PATH), timeout=API_TIMEOUT_S)
        _expect_status(response, 401)

    def read(self) -> None:
        if self.written_id is None:
            raise CheckFailed("no inspection written")
        response = self.client.get(
            self._api(INSPECTIONS_PATH),
            params={"lot_id": self.lot_id, "source": Source.SIMULATED.value},
            headers={API_KEY_HEADER: self.cfg.read_api_key},
            timeout=API_TIMEOUT_S,
        )
        _expect_status(response, 200)
        body = _json_object(response)
        if body.get("total") != 1:
            raise CheckFailed("field total")
        items = body.get("items")
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise CheckFailed("field items")
        if items[0].get("inspection_id") != self.written_id:
            raise CheckFailed("field inspection_id")

    def cors_closed(self) -> None:
        response = self.client.get(
            self._api(HEALTH_PATH),
            headers={"Origin": FOREIGN_ORIGIN},
            timeout=HEALTH_TIMEOUT_S,
        )
        if "access-control-allow-origin" in response.headers:
            raise CheckFailed("header access-control-allow-origin present")

    def dashboard(self) -> None:
        response = self.client.get(
            self.cfg.dashboard_url, follow_redirects=True, timeout=DASHBOARD_TIMEOUT_S
        )
        _expect_status(response, 200)

    def dashboard_health(self) -> None:
        url = self.cfg.dashboard_url.rstrip("/") + "/" + DASHBOARD_HEALTH_PATH
        response = self.client.get(url, timeout=DASHBOARD_TIMEOUT_S)
        _expect_status(response, 200)
        if "".join(response.text.split()) != "ok":
            raise CheckFailed("body is not ok")


def _run_check(name: str, check: Callable[[], None]) -> bool:
    try:
        check()
    except CheckFailed as exc:
        print(f"FAIL {name}: {exc}", flush=True)
        return False
    except Exception as exc:  # noqa: BLE001 (any error is a failed check)
        # Only the class name: the message of an httpx error may contain the URL (R-13).
        print(f"FAIL {name}: {type(exc).__name__}", flush=True)
        return False
    print(f"PASS {name}", flush=True)
    return True


def main(argv: Sequence[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    """Run the smoke test; returns the exit code (``transport`` is for tests)."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help (0) or an invalid option (2), already printed
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    try:
        cfg = _config(args)
    except UsageError as exc:
        print(f"smoke_test.py: error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    # TLS verification stays at the httpx default: never disabled.
    with httpx.Client(
        transport=transport,
        follow_redirects=False,
        headers={"User-Agent": "partqc-smoke-test"},
    ) as client:
        smoke = _Smoke(cfg, client)
        results = [_run_check(name, getattr(smoke, name)) for name in CHECK_NAMES]
    return EXIT_OK if all(results) else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
