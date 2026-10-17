"""Simulated lot generator (SPEC-014, RF-14, R-05, R-06).

Usage::

    uv run --package qc-api python scripts/simulate.py --lots 10 --seed 42
                                                       [--out-of-control-lots 3,7] [--dry-run]

Generates plausible ``qc_contracts.InspectionCreate`` items, always with ``source=simulated``
(there is no option to change it, R-06), and sends them to the same ingestion route as the edge
(``POST /api/v1/inspections/batch``). The ids derive from the seed, so running again with the
same seed sends the same ids and the API answers ``duplicate`` (R-05).

The API URL and the device key come from ``CLOUD_API_URL`` and ``SIM_DEVICE_API_KEY`` (or the
options of the same name); the key is never printed nor logged (R-03).

Exit codes: ``0`` success; ``1`` internal error (a generated item failed the contract);
``2`` invalid usage; ``3`` key refused (401/403); ``4`` batch refused (422); ``5`` API
unreachable or failing (health check, network errors, timeouts and 5xx after the retries).
Usage errors never repeat a value typed by the operator and never show a traceback (SPEC-027).
"""

import argparse
import json
import logging
import math
import os
import random
import re
import secrets
import sys
import textwrap
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import NoReturn
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from qc_contracts import (
    DEVICE_ID_PATTERN,
    MAX_BATCH_SIZE,
    MAX_FUTURE_SKEW,
    MODEL_VERSION_PATTERN,
    BatchCreate,
    BatchResult,
    Grade,
    InspectionCreate,
    ObjectType,
    Source,
    grade_index,
)

logger = logging.getLogger("partqc.simulate")

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_REJECTED = 4
EXIT_UNAVAILABLE = 5

HEALTH_PATH = "/api/v1/health"
BATCH_PATH = "/api/v1/inspections/batch"
HEALTH_TIMEOUT_S = 90.0
BATCH_TIMEOUT_S = 10.0
RETRY_DELAYS_S: tuple[int, ...] = (2, 4, 8)
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})

LOT_SPAN = timedelta(minutes=10)
MODEL_SHA256 = "0" * 64
DEFAULT_MODEL_VERSION = "sim-v0"
DEFAULT_LOTS = 10
DEFAULT_LOT_SIZE = 25
DEFAULT_DEFECT_RATE = 0.10
DEFAULT_UNKNOWN_RATE = 0.02
MAX_LOTS = 500
MAX_LOT_SIZE = 1000
OUT_OF_CONTROL_FACTOR = 3.0

UNKNOWN_TYPE_CONFIDENCE = (0.30, 0.69)
KNOWN_TYPE_CONFIDENCE = (0.75, 0.99)
GRADE_CONFIDENCE = (0.55, 0.95)
GRADE_SCORE_JITTER = 0.4
LATENCY_MS = (40, 180)
DEFECTIVE_GRADES: tuple[Grade, ...] = (Grade.POOR, Grade.UNUSABLE)
DEFECTIVE_WEIGHTS: tuple[float, ...] = (0.7, 0.3)
GOOD_GRADES: tuple[Grade, ...] = (Grade.PERFECT, Grade.GOOD, Grade.FAIR)
GOOD_WEIGHTS: tuple[float, ...] = (0.40, 0.35, 0.25)
TYPE_REVIEW_THRESHOLD = 0.80
GRADE_REVIEW_THRESHOLD = 0.60

# 1 to 4 digits (SEC-04 of SPEC-014): int() of a huge string would raise ValueError.
_LOT_NUMBER = re.compile(r"[0-9]{1,4}")

NOT_SHOWN = "(not shown)"
_UNRECOGNIZED = "unrecognized arguments: "
_UNRECOGNIZED_REDACTED = re.compile(r"unrecognized arguments: \d+ value\(s\) \(not shown\)")
# A value that argparse quotes with %r (a Python string literal, single or double quoted, with
# backslash escapes), with the ": " that precedes it.
_QUOTED_VALUE = re.compile(r"""(?::\s*|\s+)?(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")""")


@dataclass(frozen=True)
class SimConfig:
    """Validated arguments. Exactly one lot size mode: ``lot_size`` or the min/max pair."""

    device_id: str
    start: datetime
    seed: int
    lots: int = DEFAULT_LOTS
    lot_size: int | None = DEFAULT_LOT_SIZE
    lot_size_min: int | None = None
    lot_size_max: int | None = None
    defect_rate: float = DEFAULT_DEFECT_RATE
    out_of_control_lots: frozenset[int] = frozenset()
    unknown_rate: float = DEFAULT_UNKNOWN_RATE
    model_version: str = DEFAULT_MODEL_VERSION
    dry_run: bool = False
    api_url: str | None = None
    # repr=False: the key never shows up in a repr, a traceback or a log record (R-03).
    api_key: str | None = field(default=None, repr=False)

    def lot_rate(self, lot_number: int) -> float:
        """Probability of ``poor`` + ``unusable`` among the recognized items of a 1-based lot."""
        if lot_number in self.out_of_control_lots:
            return min(1.0, OUT_OF_CONTROL_FACTOR * self.defect_rate)
        return self.defect_rate


@dataclass(frozen=True)
class SendSummary:
    sent: int
    created: int
    duplicate: int


class SendError(Exception):
    """Sending stopped; ``exit_code`` is the process exit code. The message never has the key."""

    def __init__(self, exit_code: int, message: str, summary: SendSummary) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.summary = summary


# ---------------------------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------------------------


def redact_usage_error(message: str) -> str:
    """``message`` of an argparse usage error without any value typed by the operator.

    The list of ``unrecognized arguments`` becomes a count, and every value argparse quotes
    (``invalid int value: '<value>'``, ``ignored explicit argument '<value>'``...) becomes
    ``(not shown)``. The simulator's own messages have no quotes and are kept as they are.
    """
    if message.startswith(_UNRECOGNIZED):
        if _UNRECOGNIZED_REDACTED.fullmatch(message):
            return message
        count = len(message[len(_UNRECOGNIZED) :].split())
        return f"{_UNRECOGNIZED}{count} value(s) {NOT_SHOWN}"
    return _QUOTED_VALUE.sub(f" {NOT_SHOWN}", message)


class NoEchoArgumentParser(argparse.ArgumentParser):
    """``ArgumentParser`` whose usage errors never repeat a typed value (SEC-01 of SPEC-014).

    A mistyped option can carry the device key (``--api-keyy <key>``), and argparse would print
    it on stderr. The usage line and the exit code 2 stay as in ``ArgumentParser``.
    """

    def parse_args(
        self, args: Sequence[str] | None = None, namespace: argparse.Namespace | None = None
    ) -> argparse.Namespace:
        parsed, extras = self.parse_known_args(args, namespace)
        if extras:
            # The exact count, even when a value contains spaces.
            self.error(f"{_UNRECOGNIZED}{len(extras)} value(s) {NOT_SHOWN}")
        return parsed

    def error(self, message: str) -> NoReturn:
        super().error(redact_usage_error(message))


class _HelpFormatter(argparse.HelpFormatter):
    """Never splits a word of the help at a hyphen (``--api-key=<value>`` stays whole)."""

    def _split_lines(self, text: str, width: int) -> list[str]:
        text = " ".join(text.split())
        return textwrap.wrap(text, width, break_on_hyphens=False, break_long_words=False)


def _build_parser() -> argparse.ArgumentParser:
    parser = NoEchoArgumentParser(
        prog="simulate.py",
        description=(
            "Generate simulated inspection lots (always source=simulated) and send them to the "
            "qc-api batch route."
        ),
        # No prefix matching: only the exact option names are accepted.
        allow_abbrev=False,
        formatter_class=_HelpFormatter,
    )
    parser.add_argument(
        "--api-url",
        help="API base URL (default: CLOUD_API_URL); https://, or http:// for localhost only",
    )
    parser.add_argument(
        "--device-id", help="simulator device id (default: SIM_DEVICE_ID), e.g. sim-01"
    )
    parser.add_argument(
        "--api-key",
        help=(
            "device API key (default: SIM_DEVICE_API_KEY). Prefer the environment variable: "
            "a value on the command line ends up in the shell history and the process list. "
            "On the command line, use the form --api-key=<value>: a key that starts with '-' "
            "does not work after a space"
        ),
    )
    parser.add_argument("--lots", type=int, default=DEFAULT_LOTS, help="number of lots (1-500)")
    parser.add_argument(
        "--lot-size",
        type=int,
        help=f"items per lot, 1-{MAX_LOT_SIZE} (default {DEFAULT_LOT_SIZE})",
    )
    parser.add_argument("--lot-size-min", type=int, help="random lot size: lower bound")
    parser.add_argument("--lot-size-max", type=int, help="random lot size: upper bound")
    parser.add_argument(
        "--defect-rate",
        type=float,
        default=DEFAULT_DEFECT_RATE,
        help="base probability of poor + unusable among recognized items (0-1)",
    )
    parser.add_argument(
        "--out-of-control-lots",
        default="",
        help="comma-separated 1-based lot numbers whose defect rate is 3x the base, e.g. 3,7",
    )
    parser.add_argument(
        "--unknown-rate",
        type=float,
        default=DEFAULT_UNKNOWN_RATE,
        help="probability of an unknown object (0-1)",
    )
    parser.add_argument(
        "--start",
        help="ISO 8601 start with a time zone (default: now - lots x 10 min)",
    )
    parser.add_argument("--seed", type=int, help="random seed >= 0 (default: random)")
    parser.add_argument(
        "--model-version", default=DEFAULT_MODEL_VERSION, help="model_version of the items"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the items as JSON Lines and send nothing",
    )
    return parser


def parse_args(argv: Sequence[str] | None, *, now: datetime | None = None) -> SimConfig:
    """Parse and validate ``argv``; ``now`` (aware) replaces the clock.

    Invalid usage exits through ``argparse`` (``SystemExit(2)``, message on stderr).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    now = _aware_now(now)

    device_id = args.device_id if args.device_id is not None else _env("SIM_DEVICE_ID")
    # fullmatch, never match/search: "$" would accept a trailing "\n" (architecture.md 3.2).
    if re.fullmatch(DEVICE_ID_PATTERN, device_id) is None:
        parser.error(f"--device-id (or SIM_DEVICE_ID) must match {DEVICE_ID_PATTERN}")
    if re.fullmatch(MODEL_VERSION_PATTERN, args.model_version) is None:
        parser.error(f"--model-version must match {MODEL_VERSION_PATTERN}")

    if not 1 <= args.lots <= MAX_LOTS:
        parser.error(f"--lots must be in 1..{MAX_LOTS}")
    lot_size, lot_size_min, lot_size_max = _lot_sizes(parser, args)
    defect_rate = _rate(parser, "--defect-rate", args.defect_rate)
    unknown_rate = _rate(parser, "--unknown-rate", args.unknown_rate)
    out_of_control = _out_of_control_lots(parser, args.out_of_control_lots, args.lots)

    if args.seed is not None and args.seed < 0:
        parser.error("--seed must be >= 0")
    seed = args.seed if args.seed is not None else secrets.randbits(32)

    start = _start(parser, args.start, now, args.lots)
    largest = lot_size if lot_size is not None else lot_size_max
    if _last_inspected_at(start, args.lots, largest) > now + MAX_FUTURE_SKEW:
        parser.error("--start is too late: generated inspections would be more than 5 min ahead")

    api_url: str | None = None
    api_key: str | None = None
    if not args.dry_run:
        api_url = _api_url(parser, args.api_url)
        api_key = _api_key(parser, args.api_key)

    return SimConfig(
        device_id=device_id,
        start=start,
        seed=seed,
        lots=args.lots,
        lot_size=lot_size,
        lot_size_min=lot_size_min,
        lot_size_max=lot_size_max,
        defect_rate=defect_rate,
        out_of_control_lots=out_of_control,
        unknown_rate=unknown_rate,
        model_version=args.model_version,
        dry_run=args.dry_run,
        api_url=api_url,
        api_key=api_key,
    )


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _aware_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(UTC)


def _lot_sizes(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> tuple[int | None, int | None, int | None]:
    has_min, has_max = args.lot_size_min is not None, args.lot_size_max is not None
    if args.lot_size is not None and (has_min or has_max):
        parser.error("--lot-size cannot be combined with --lot-size-min/--lot-size-max")
    if has_min != has_max:
        parser.error("--lot-size-min and --lot-size-max must be given together")
    if has_min:
        low, high = args.lot_size_min, args.lot_size_max
        if not (1 <= low <= MAX_LOT_SIZE and 1 <= high <= MAX_LOT_SIZE):
            parser.error(f"--lot-size-min and --lot-size-max must be in 1..{MAX_LOT_SIZE}")
        if low > high:
            parser.error("--lot-size-min must be <= --lot-size-max")
        return None, low, high
    lot_size = DEFAULT_LOT_SIZE if args.lot_size is None else args.lot_size
    if not 1 <= lot_size <= MAX_LOT_SIZE:
        parser.error(f"--lot-size must be in 1..{MAX_LOT_SIZE}")
    return lot_size, None, None


def _rate(parser: argparse.ArgumentParser, name: str, value: float) -> float:
    # The negated comparison also rejects NaN.
    if not (math.isfinite(value) and 0.0 <= value <= 1.0):
        parser.error(f"{name} must be in 0..1")
    return value


def _out_of_control_lots(parser: argparse.ArgumentParser, raw: str, lots: int) -> frozenset[int]:
    if not raw.strip():
        return frozenset()
    numbers: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if _LOT_NUMBER.fullmatch(token) is None:
            parser.error("--out-of-control-lots must be a comma-separated list of lot numbers")
        numbers.append(int(token))
    if any(not 1 <= number <= lots for number in numbers):
        parser.error(f"--out-of-control-lots must be in 1..{lots}")
    if len(set(numbers)) != len(numbers):
        parser.error("--out-of-control-lots must not repeat a lot")
    return frozenset(numbers)


def _start(parser: argparse.ArgumentParser, raw: str | None, now: datetime, lots: int) -> datetime:
    if raw is None:
        return now - lots * LOT_SPAN
    try:
        start = datetime.fromisoformat(raw)
    except ValueError:
        parser.error("--start must be an ISO 8601 date-time with a time zone")
    if start.utcoffset() is None:
        parser.error("--start must have a time zone (e.g. 2026-11-01T12:00:00Z)")
    try:
        return start.astimezone(UTC)
    except OverflowError:
        parser.error("--start is out of range")


def _last_inspected_at(start: datetime, lots: int, largest_lot: int) -> datetime:
    """Latest possible ``inspected_at``: last item of the last lot with the largest size."""
    try:
        return start + (lots - 1) * LOT_SPAN + _item_offset(largest_lot - 1, largest_lot)
    except OverflowError:
        return datetime.max.replace(tzinfo=UTC)


def _item_offset(j: int, n: int) -> timedelta:
    """Offset of item ``j`` (0-based) of a lot of ``n`` items, evenly spaced in 10 min."""
    return LOT_SPAN * j / n


def _api_url(parser: argparse.ArgumentParser, raw: str | None) -> str:
    url = raw if raw is not None else os.environ.get("CLOUD_API_URL", "")
    if not url.strip():
        parser.error("no API URL: set CLOUD_API_URL or pass --api-url (or use --dry-run)")
    # The value is never echoed: it might carry credentials (R-03).
    # Visible ASCII only, before urlsplit: a space, a control character, DEL or a non-ASCII
    # character would reach httpx (InvalidURL, traceback) or a terminal (SEC-03 of SPEC-014).
    if not all("!" <= ch <= "~" for ch in url):
        parser.error(f"invalid --api-url {NOT_SHOWN}")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        has_userinfo = parts.username is not None or parts.password is not None
        _ = parts.port  # raises ValueError for an invalid port
        # The host as httpx encodes it for the request (IDNAError, a ValueError, for an
        # invalid "xn--" label), so the client never raises on it later.
        _ = httpx.URL(url).host
    except (ValueError, httpx.InvalidURL):
        parser.error(f"invalid --api-url {NOT_SHOWN}")
    if not host or has_userinfo or parts.query or parts.fragment:
        parser.error("invalid --api-url: expected scheme://host[:port][/path], no credentials")
    if not (parts.scheme == "https" or (parts.scheme == "http" and host in LOCAL_HOSTS)):
        parser.error("--api-url must use https:// (http:// only for localhost or 127.0.0.1)")
    return url.rstrip("/")


def _api_key(parser: argparse.ArgumentParser, raw: str | None) -> str:
    key = raw if raw is not None else _env("SIM_DEVICE_API_KEY")
    if not key:
        parser.error("no API key: set SIM_DEVICE_API_KEY (or pass --api-key, or use --dry-run)")
    # A header value must be visible ASCII; the key itself is never echoed.
    if not all("!" <= ch <= "~" for ch in key):
        parser.error("invalid API key (not shown): expected visible ASCII characters only")
    return key


# ---------------------------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------------------------


def generate(cfg: SimConfig) -> list[InspectionCreate]:
    """Items of every lot, in order; deterministic for a given ``cfg``.

    A single ``random.Random(cfg.seed)`` is consumed in this fixed order (changing it changes
    every id and value, so CA-02 of SPEC-014 depends on it):

    for each lot ``i`` = 1..lots:
      0. only with ``--lot-size-min/--lot-size-max``: ``n = randint(min, max)``;
    for each item of the lot:
      1. ``getrandbits(128)`` -> ``inspection_id`` (UUID version 4);
      2. ``random()`` -> unknown when ``< unknown_rate``;
      3. unknown: ``uniform(0.30, 0.69)`` -> ``type_confidence``;
         recognized: ``random()`` -> ``screw`` when ``< 0.5`` else ``nut``;
         ``uniform(0.75, 0.99)`` -> ``type_confidence``; ``random()`` -> defective when
         ``< lot rate``; ``choices(grades, weights)`` -> ``grade``; ``uniform(0.55, 0.95)`` ->
         ``grade_confidence``; ``uniform(-0.4, 0.4)`` -> ``grade_score`` jitter;
      4. ``randint(40, 180)`` -> ``latency_ms``.

    Every item goes through ``InspectionCreate``; a ``ValidationError`` is a programming error.
    """
    rng = random.Random(cfg.seed)
    items: list[InspectionCreate] = []
    for lot_number in range(1, cfg.lots + 1):
        if cfg.lot_size is not None:
            n = cfg.lot_size
        else:
            assert cfg.lot_size_min is not None and cfg.lot_size_max is not None
            n = rng.randint(cfg.lot_size_min, cfg.lot_size_max)
        lot_id = f"SIM-{cfg.start:%Y%m%d}-{lot_number:03d}"
        lot_start = cfg.start + (lot_number - 1) * LOT_SPAN
        rate = cfg.lot_rate(lot_number)
        for j in range(n):
            items.append(
                _item(rng, cfg, lot_id, lot_start + _item_offset(j, n), rate),
            )
    return items


def _item(
    rng: random.Random, cfg: SimConfig, lot_id: str, inspected_at: datetime, rate: float
) -> InspectionCreate:
    inspection_id = uuid.UUID(int=rng.getrandbits(128), version=4)
    grade: Grade | None
    grade_score: float | None
    grade_confidence: float | None
    if rng.random() < cfg.unknown_rate:
        object_type = ObjectType.UNKNOWN
        type_confidence = rng.uniform(*UNKNOWN_TYPE_CONFIDENCE)
        grade = grade_score = grade_confidence = None
    else:
        object_type = ObjectType.SCREW if rng.random() < 0.5 else ObjectType.NUT
        type_confidence = rng.uniform(*KNOWN_TYPE_CONFIDENCE)
        if rng.random() < rate:
            grade = rng.choices(DEFECTIVE_GRADES, weights=DEFECTIVE_WEIGHTS)[0]
        else:
            grade = rng.choices(GOOD_GRADES, weights=GOOD_WEIGHTS)[0]
        grade_confidence = rng.uniform(*GRADE_CONFIDENCE)
        jitter = rng.uniform(-GRADE_SCORE_JITTER, GRADE_SCORE_JITTER)
        grade_score = min(4.0, max(0.0, grade_index(grade) + jitter))
    latency_ms = rng.randint(*LATENCY_MS)
    needs_review = type_confidence < TYPE_REVIEW_THRESHOLD or (
        grade_confidence is not None and grade_confidence < GRADE_REVIEW_THRESHOLD
    )
    return InspectionCreate(
        inspection_id=inspection_id,
        device_id=cfg.device_id,
        lot_id=lot_id,
        inspected_at=inspected_at,
        object_type=object_type,
        grade=grade,
        grade_score=grade_score,
        type_confidence=type_confidence,
        grade_confidence=grade_confidence,
        needs_review=needs_review,
        model_version=cfg.model_version,
        model_sha256=MODEL_SHA256,
        latency_ms=latency_ms,
        source=Source.SIMULATED,
    )


# ---------------------------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------------------------


def send(
    items: Sequence[InspectionCreate],
    cfg: SimConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], object] = time.sleep,
) -> SendSummary:
    """Health check, then batches of up to 100 items; raises ``SendError`` on failure."""
    if cfg.dry_run or cfg.api_url is None or cfg.api_key is None:
        raise ValueError("send() needs api_url and api_key and is not used with --dry-run")
    sent = created = duplicate = 0
    with httpx.Client(base_url=cfg.api_url, transport=transport) as client:
        _check_health(client)
        headers = {"X-API-Key": cfg.api_key}
        for offset in range(0, len(items), MAX_BATCH_SIZE):
            chunk = list(items[offset : offset + MAX_BATCH_SIZE])
            body = BatchCreate(items=chunk).model_dump_json()
            try:
                result = _post_batch(client, body, headers, len(chunk), sleep)
            except _BatchError as exc:
                raise SendError(
                    exc.exit_code, str(exc), SendSummary(sent, created, duplicate)
                ) from None
            sent += len(chunk)
            for item_result in result.results:
                if item_result.status == "created":
                    created += 1
                else:
                    duplicate += 1
    return SendSummary(sent=sent, created=created, duplicate=duplicate)


class _BatchError(Exception):
    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _check_health(client: httpx.Client) -> None:
    try:
        response = client.get(HEALTH_PATH, timeout=HEALTH_TIMEOUT_S)
    except httpx.RequestError as exc:
        raise SendError(
            EXIT_UNAVAILABLE,
            f"health check failed: {type(exc).__name__}",
            SendSummary(0, 0, 0),
        ) from None
    if response.status_code != httpx.codes.OK:
        raise SendError(
            EXIT_UNAVAILABLE,
            f"health check failed: HTTP {response.status_code}",
            SendSummary(0, 0, 0),
        )


def _post_batch(
    client: httpx.Client,
    body: str,
    headers: dict[str, str],
    expected: int,
    sleep: Callable[[float], object],
) -> BatchResult:
    """One batch with up to 3 retries (2, 4 and 8 s) on network errors, timeouts and 5xx."""
    attempts = len(RETRY_DELAYS_S) + 1
    last_error = ""
    for attempt in range(attempts):
        if attempt:
            sleep(RETRY_DELAYS_S[attempt - 1])
        try:
            response = client.post(
                BATCH_PATH,
                content=body,
                headers={**headers, "Content-Type": "application/json"},
                timeout=BATCH_TIMEOUT_S,
            )
        except httpx.RequestError as exc:
            last_error = type(exc).__name__
            continue
        status = response.status_code
        if status >= httpx.codes.INTERNAL_SERVER_ERROR:
            last_error = f"HTTP {status}"
            continue
        if status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise _BatchError(EXIT_AUTH, f"API key refused: HTTP {status}")
        if status == httpx.codes.UNPROCESSABLE_ENTITY:
            raise _BatchError(EXIT_REJECTED, f"batch refused: HTTP 422 {_detail(response)}")
        if not response.is_success:
            raise _BatchError(EXIT_UNAVAILABLE, f"unexpected response: HTTP {status}")
        return _batch_result(response, expected)
    raise _BatchError(
        EXIT_UNAVAILABLE, f"batch failed after {attempts} attempts (last: {last_error})"
    )


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json()["detail"]
    except (ValueError, KeyError, TypeError):
        return "(no detail)"
    return detail if isinstance(detail, str) else _compact_json(detail)


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _batch_result(response: httpx.Response, expected: int) -> BatchResult:
    try:
        result = BatchResult.model_validate_json(response.content)
    except ValidationError:
        raise _BatchError(EXIT_UNAVAILABLE, "unexpected batch response body") from None
    if len(result.results) != expected:
        raise _BatchError(
            EXIT_UNAVAILABLE,
            f"unexpected batch response: {len(result.results)} results for {expected} items",
        )
    return result


# ---------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _summary(cfg: SimConfig, sent: int, result: SendSummary | None) -> str:
    counts = "" if result is None else f" created={result.created} duplicate={result.duplicate}"
    return f"sent={sent}{counts} lots={cfg.lots} seed={cfg.seed} source={Source.SIMULATED}\n"


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], object] = time.sleep,
    now: datetime | None = None,
) -> int:
    """CLI entry point; returns the exit code (see the module docstring)."""
    _configure_logging()
    try:
        cfg = parse_args(argv, now=now)
    except SystemExit as exc:  # argparse: 2 on invalid usage, 0 on --help
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE

    try:
        items = generate(cfg)
    except ValidationError as exc:
        # Only the number of errors: the details would repeat generated values.
        logger.error(
            "internal error: a generated item failed the contract (%d errors)", exc.error_count()
        )
        return EXIT_INTERNAL

    if cfg.dry_run:
        sys.stdout.writelines(item.model_dump_json() + "\n" for item in items)
        sys.stdout.flush()
        sys.stderr.write(_summary(cfg, len(items), None))
        return EXIT_OK

    try:
        result = send(items, cfg, transport=transport, sleep=sleep)
    except SendError as exc:
        partial = exc.summary
        logger.error(
            "%s (sent=%d created=%d duplicate=%d seed=%d)",
            exc,
            partial.sent,
            partial.created,
            partial.duplicate,
            cfg.seed,
        )
        return exc.exit_code
    sys.stdout.write(_summary(cfg, result.sent, result))
    sys.stdout.flush()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
