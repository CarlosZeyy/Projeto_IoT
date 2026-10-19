"""CHANGELOG entry of a model version from its ``metrics.json`` (SPEC-012 section 4.8).

Display rule of ``docs/architecture.md`` section 7 ("Exibição das métricas"), the same as the
dashboard: 4 decimals with a decimal comma, from ``Decimal(repr(value))``, never toward the
target (``ROUND_CEILING`` when lower is better, ``ROUND_FLOOR`` otherwise); a 95% interval has
``low`` cut down and ``high`` rounded up; integers without decimals. The status against the PRD
target always uses the raw value.

No torch, no sklearn here (CA-27).

CLI::

    python -m qc_ml.report changelog --model-dir ml/models/partqc-mnv3-v1 \
        [--previous ml/models/partqc-mnv3-v0] [--append ml/models/CHANGELOG.md]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Literal

from qc_ml.artifacts import METRICS_FILE
from qc_ml.steps import EXIT_ERROR, EXIT_OK

PLACES = Decimal("0.0001")
EMPTY = "—"
STATUS_MET = "atingida"
STATUS_BELOW = "abaixo da meta"
STATUS_UNKNOWN = "n/d"

# docs/architecture.md section 7: metrics in which lower is better (shown rounded up).
LOWER_IS_BETTER: frozenset[str] = frozenset(
    {"grade_mae", "false_unknown_rate", "needs_review_rate", "latency_ms_p50", "latency_ms_p95"}
)


@dataclass(frozen=True)
class Target:
    """A target of the PRD section 7."""

    op: Literal[">=", "<="]
    threshold: str  # decimal text, e.g. "0.95"

    def describe(self) -> str:
        symbol = "≥" if self.op == ">=" else "≤"
        return f"{symbol} {self.threshold.replace('.', ',')}"

    def status(self, value: Any) -> str:
        if not _is_number(value):
            return STATUS_UNKNOWN
        limit = float(self.threshold)
        met = value >= limit if self.op == ">=" else value <= limit
        return STATUS_MET if met else STATUS_BELOW


PRD_TARGETS: dict[str, Target] = {
    "type_accuracy": Target(">=", "0.95"),
    "grade_qwk": Target(">=", "0.75"),
    "grade_off_by_one_accuracy": Target(">=", "0.90"),
    "unusable_recall": Target(">=", "0.90"),
    "defective_recall": Target(">=", "0.90"),
    "latency_ms_p95": Target("<=", "300"),
}

# Integers shown without decimals (counts).
INTEGER_KEYS: frozenset[str] = frozenset({"latency_runs"})

# Rows of the table, in order: (metrics.json key, PT-BR description).
TABLE_ROWS: tuple[tuple[str, str], ...] = (
    ("type_accuracy", "acurácia de tipo"),
    ("grade_qwk", "QWK do grau"),
    ("grade_qwk_ci95", "IC 95% do QWK, bootstrap por peça"),
    ("grade_off_by_one_accuracy", "acurácia do grau com tolerância ±1"),
    ("grade_mae", "erro absoluto médio do grau, em níveis"),
    ("unusable_recall", "recall de inutilizável"),
    ("unusable_recall_ci95", "IC 95% do recall de inutilizável"),
    ("unusable_precision", "precisão de inutilizável"),
    ("defective_recall", "recall de defeituosa: ruim ou inutilizável"),
    ("defective_recall_ci95", "IC 95% do recall de defeituosa"),
    ("defective_precision", "precisão de defeituosa"),
    ("unknown_rate_on_other", "taxa de desconhecido em outros objetos"),
    ("false_unknown_rate", "taxa de falso desconhecido"),
    ("needs_review_rate", "taxa de revisão"),
    ("latency_ms_p50", "latência p50 em ms"),
    ("latency_ms_p95", "latência p95 em ms"),
    ("latency_runs", "medições de latência"),
)


def _is_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isfinite(value)


def _quantized(value: float | int, rounding: str) -> str:
    text = format(Decimal(repr(value)).quantize(PLACES, rounding=rounding), "f")
    return text.replace(".", ",")


def format_metric(value: Any, key: str | None = None) -> str:
    """One value by the display rule; ``None`` -> ``—``."""
    if value is None:
        return EMPTY
    if key in INTEGER_KEYS and isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if _is_number(value):
        rounding = ROUND_CEILING if key in LOWER_IS_BETTER else ROUND_FLOOR
        return _quantized(value, rounding)
    if isinstance(value, list | tuple) and len(value) == 2 and all(map(_is_number, value)):
        low = _quantized(value[0], ROUND_FLOOR)
        high = _quantized(value[1], ROUND_CEILING)
        return f"[{low}; {high}]"
    return str(value)


def load_metrics(model_dir: Path | str) -> dict[str, Any]:
    path = Path(model_dir) / METRICS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"{METRICS_FILE} not found in {model_dir}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object")
    return data


def _entry_date(metrics: Mapping[str, Any]) -> str:
    value = metrics.get("evaluated_at")
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except ValueError:
        return "AAAA-MM-DD"


def changelog_entry(metrics: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> str:
    """Markdown of one entry: ``## <version> — <date>``, the metric table and the sections."""
    version = metrics.get("model_version", "?")
    lines = [f"## {version} — {_entry_date(metrics)}", ""]
    lines += [
        f"- `model_sha256`: `{metrics.get('model_sha256')}`",
        f"- Split: `{metrics.get('split_file')}` (`split_sha256` "
        f"`{metrics.get('split_sha256')}`); `manifest_sha256` `{metrics.get('manifest_sha256')}`",
        "- Limiares (`decision.json`, escolhidos na validação): "
        f"`{json.dumps(metrics.get('decision'))}`",
        f"- Latência medida em: {metrics.get('latency_machine') or EMPTY}",
        "- Valores do `metrics.json` (teste), exibidos com 4 casas e nunca a favor da meta "
        "(`docs/architecture.md` §7); o status usa o valor bruto.",
        "",
    ]
    header = "| Métrica | Valor | Meta (PRD §7) | Status |"
    rule = "|---|---|---|---|"
    if previous is not None:
        header += f" Anterior ({previous.get('model_version', '?')}) |"
        rule += "---|"
    lines += [header, rule]
    for key, description in TABLE_ROWS:
        value = metrics.get(key)
        target = PRD_TARGETS.get(key)
        row = (
            f"| `{key}` ({description}) | {format_metric(value, key)} | "
            f"{target.describe() if target else EMPTY} | "
            f"{target.status(value) if target else EMPTY} |"
        )
        if previous is not None:
            row += f" {format_metric(previous.get(key), key)} |"
        lines.append(row)
    lines.append("")
    items = metrics.get("n_items_test_by_grade") or {}
    if isinstance(items, Mapping) and items:
        shown = ", ".join(f"{grade}: {count}" for grade, count in items.items())
        lines += [f"Peças no teste por grau: {shown}.", ""]
    lines += ["### O que mudou", "", "_(a preencher)_", "", "### Problemas conhecidos", ""]
    warnings = metrics.get("warnings") or []
    lines += [f"- {warning}" for warning in warnings] if warnings else []
    lines += ["- _(a preencher)_", ""]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qc_ml.report", description="Reports of a model version."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    changelog = commands.add_parser("changelog", help="CHANGELOG entry from metrics.json")
    changelog.add_argument("--model-dir", required=True, type=Path)
    changelog.add_argument("--previous", type=Path, default=None)
    changelog.add_argument("--append", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Print the entry; with ``--append``, also add it to the end of the given file."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR
    try:
        metrics = load_metrics(args.model_dir)
        previous = load_metrics(args.previous) if args.previous else None
    except (OSError, ValueError) as exc:
        print(f"report failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    entry = changelog_entry(metrics, previous)
    print(entry)
    if args.append is not None:
        try:
            current = args.append.read_text(encoding="utf-8") if args.append.exists() else ""
            separator = "" if not current or current.endswith("\n\n") else "\n"
            if current and not current.endswith("\n"):
                separator = "\n\n"
            with args.append.open("a", encoding="utf-8") as fh:
                fh.write(separator + entry)
        except OSError as exc:
            print(f"report failed: {exc}", file=sys.stderr)
            return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
