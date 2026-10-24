"""CHANGELOG entry of a model version from its ``metrics.json`` (SPEC-012 section 4.8).

Display rule of ``docs/architecture.md`` section 7 ("Exibição das métricas"), the same as the
dashboard: 4 decimals with a decimal comma, from ``Decimal(repr(value))``, never toward the
target (``ROUND_CEILING`` when lower is better, ``ROUND_FLOOR`` otherwise); a 95% interval has
``low`` cut down and ``high`` rounded up; integers without decimals. The status against the PRD
target always uses the raw value.

The entry has a ``### Dados`` section with the external images by split and one credit line per
external source (SPEC-035 section 4.6). ``release-notes`` writes the notes of the GitHub Release
of the model, with the same source lines plus the licence and source links; it fails (exit 2)
when a source used in train is not in the registry, so that no notes without the full credit
are ever generated.

No torch, no sklearn here (CA-27).

CLI::

    python -m qc_ml.report changelog --model-dir ml/models/partqc-mnv3-v1 \
        [--previous ml/models/partqc-mnv3-v0] [--append ml/models/CHANGELOG.md] \
        [--external-sources ml/external_sources.csv]
    python -m qc_ml.report release-notes --model-dir ml/models/partqc-mnv3-v1 \
        [--external-sources ml/external_sources.csv] [--output <file>]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal

from qc_ml.artifacts import METRICS_FILE, read_model_sha256
from qc_ml.data import (
    DEFAULT_EXTERNAL_SOURCES,
    SOURCE_ID_PATTERN,
    ExternalSource,
    load_external_sources,
)
from qc_ml.errors import ManifestError, ModelArtifactError
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

NOT_IN_REGISTRY = "licença não encontrada no registro"
INVALID_SOURCE_ID = "<invalid source_id>"
NOTES_HEADING = "## Fontes externas e créditos"
NOTES_NO_EXTERNAL = "Este modelo não usa imagens externas (ADR-020)."
NOTES_FOOTER = (
    "Registro das fontes: `ml/external_sources.csv`. Histórico do modelo: `ml/models/CHANGELOG.md`."
)

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


def _counts_of(metrics: Mapping[str, Any], split: str) -> Mapping[str, Any]:
    counts = metrics.get("counts")
    value = counts.get(split) if isinstance(counts, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def _has_origins(metrics: Mapping[str, Any]) -> bool:
    """``counts`` has ``by_origin`` (a ``metrics.json`` written after SPEC-035)."""
    return any("by_origin" in _counts_of(metrics, split) for split in ("train", "val", "test"))


def _external_images(metrics: Mapping[str, Any], split: str) -> Any:
    by_origin = _counts_of(metrics, split).get("by_origin")
    return by_origin.get("external", 0) if isinstance(by_origin, Mapping) else 0


def train_sources(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """``counts.train.by_source`` (``{}`` when absent, as in a ``metrics.json`` before SPEC-035).

    Raises:
        ValueError: ``by_source`` is present but is not a JSON object.
    """
    by_source = _counts_of(metrics, "train").get("by_source")
    if by_source is None:
        return {}
    if not isinstance(by_source, Mapping):
        raise ValueError("counts.train.by_source in metrics.json must be a JSON object")
    return dict(by_source)


def shown_source_id(source_id: str) -> str:
    """The ``source_id`` itself when it has the registry format, else ``<invalid source_id>``
    (a value from ``metrics.json`` is never echoed if it could carry control characters)."""
    return source_id if SOURCE_ID_PATTERN.fullmatch(source_id) else INVALID_SOURCE_ID


def source_lines(
    by_source: Mapping[str, Any], registry: Mapping[str, ExternalSource]
) -> list[tuple[str, str, ExternalSource | None]]:
    """``(source_id, line, source)`` per source, in ``source_id`` order (SPEC-035 4.6).

    The single function behind the ``### Dados`` section and the Release notes, so that the
    order and the counts of the two never differ. ``source`` is ``None`` when the source is not
    in the registry (the line then ends with ``licença não encontrada no registro``).
    """
    result: list[tuple[str, str, ExternalSource | None]] = []
    for source_id in sorted(by_source):
        n = by_source[source_id]
        source = registry.get(source_id)
        head = f"- `{shown_source_id(source_id)}`: {n} imagens"
        if source is None:
            result.append((source_id, f"{head}, {NOT_IN_REGISTRY}", None))
        else:
            line = f"{head}, {source.license}. Crédito: {source.attribution}"
            result.append((source_id, line, source))
    return result


def _fraction_ceiling(numerator: Any, denominator: Any) -> str:
    """``numerator / denominator`` with 4 decimals, decimal comma, rounded up (exact)."""
    if not (isinstance(numerator, int) and isinstance(denominator, int)) or denominator <= 0:
        return EMPTY
    scaled = math.ceil(Fraction(numerator, denominator) * 10000)
    return f"{scaled // 10000},{scaled % 10000:04d}"


def data_section(metrics: Mapping[str, Any], registry: Mapping[str, ExternalSource]) -> list[str]:
    """Lines of ``### Dados`` (empty for a ``metrics.json`` without ``by_origin``)."""
    if not _has_origins(metrics):
        return []
    e_train = _external_images(metrics, "train")
    n_train = _counts_of(metrics, "train").get("n_images", 0)
    lines = [
        "### Dados",
        "",
        f"- Validação e teste: {_external_images(metrics, 'val')} e "
        f"{_external_images(metrics, 'test')} imagens externas (ADR-020).",
        f"- Treino: {e_train} imagens externas de {n_train} "
        f"({_fraction_ceiling(e_train, n_train)}).",
    ]
    lines += [line for _, line, _ in source_lines(train_sources(metrics), registry)]
    return [*lines, ""]


def changelog_entry(
    metrics: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
    registry: Mapping[str, ExternalSource] | None = None,
) -> str:
    """Markdown of one entry: ``## <version> — <date>``, the metric table and the sections.

    ``registry`` (``source_id -> ExternalSource``) gives the licence and credit of the sources
    in the ``### Dados`` section; ``None`` is an empty registry.
    """
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
    lines += data_section(metrics, registry or {})
    lines += ["### O que mudou", "", "_(a preencher)_", "", "### Problemas conhecidos", ""]
    warnings = metrics.get("warnings") or []
    lines += [f"- {warning}" for warning in warnings] if warnings else []
    lines += ["- _(a preencher)_", ""]
    return "\n".join(lines)


class ReleaseNotesError(ValueError):
    """The Release notes cannot be generated (``release-notes`` exits with 2)."""


def release_notes(
    model_sha256: str, metrics: Mapping[str, Any], registry: Mapping[str, ExternalSource]
) -> str:
    """Markdown of the GitHub Release notes (SPEC-035 section 4.6), ending with one ``\\n``.

    Raises:
        ReleaseNotesError: a source of ``counts.train.by_source`` is not in the registry; the
            message has one ``source not in registry: <source_id>`` line per missing source, in
            ``source_id`` order (``<invalid source_id>`` for an id outside the registry format).
        ValueError: ``counts.train.by_source`` is not a JSON object.
    """
    lines = source_lines(train_sources(metrics), registry)
    missing = [source_id for source_id, _, source in lines if source is None]
    if missing:
        raise ReleaseNotesError(
            "\n".join(f"source not in registry: {shown_source_id(s)}" for s in missing)
        )
    if lines:
        body = "\n".join(
            f"{line} | Licença: {source.license_url} | Fonte: {source.url}"
            for _, line, source in lines
            if source is not None
        )
    else:
        body = NOTES_NO_EXTERNAL
    blocks = [f"sha256: {model_sha256}", NOTES_HEADING, body, NOTES_FOOTER]
    return "\n\n".join(blocks) + "\n"


def _load_registry(path: Path | None) -> dict[str, ExternalSource]:
    return load_external_sources(DEFAULT_EXTERNAL_SOURCES if path is None else path)


def _write_atomic(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _write_stdout(text: str) -> None:
    """``text`` as UTF-8 bytes, so that stdout and ``--output`` are the same byte for byte."""
    sys.stdout.flush()
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        sys.stdout.flush()
        return
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def _print_problems(problems: Sequence[Any]) -> None:
    for problem in problems:
        print(problem, file=sys.stderr)


def _release_notes_main(args: argparse.Namespace) -> int:
    """Every check runs before ``--output`` is opened; on error nothing is written."""
    try:
        digest = read_model_sha256(args.model_dir)
        metrics = load_metrics(args.model_dir)
        registry = _load_registry(args.external_sources)
        text = release_notes(digest, metrics, registry)
    except ReleaseNotesError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    except ManifestError as exc:
        print(
            "release-notes failed: the registry of the external sources has problems",
            file=sys.stderr,
        )
        _print_problems(exc.problems)
        return EXIT_ERROR
    except (OSError, ValueError, ModelArtifactError) as exc:
        print(f"release-notes failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if args.output is None:
        _write_stdout(text)
        return EXIT_OK
    try:
        _write_atomic(args.output, text.encode("utf-8"))
    except OSError as exc:
        print(f"release-notes failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qc_ml.report", description="Reports of a model version."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    changelog = commands.add_parser("changelog", help="CHANGELOG entry from metrics.json")
    changelog.add_argument("--model-dir", required=True, type=Path)
    changelog.add_argument("--previous", type=Path, default=None)
    changelog.add_argument("--append", type=Path, default=None)
    notes = commands.add_parser("release-notes", help="notes of the GitHub Release of the model")
    notes.add_argument("--model-dir", required=True, type=Path)
    notes.add_argument("--output", type=Path, default=None)
    for command in (changelog, notes):
        command.add_argument(
            "--external-sources",
            type=Path,
            default=None,
            help="registry of the external sources (default: ml/external_sources.csv)",
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """``changelog``: print the entry (with ``--append``, also add it to the end of the file).
    ``release-notes``: print or write the Release notes. 0 on success, 2 on any error."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR
    if args.command == "release-notes":
        return _release_notes_main(args)
    try:
        metrics = load_metrics(args.model_dir)
        previous = load_metrics(args.previous) if args.previous else None
        registry = _load_registry(args.external_sources)
    except ManifestError as exc:
        print("report failed: the registry of the external sources has problems", file=sys.stderr)
        _print_problems(exc.problems)
        return EXIT_ERROR
    except (OSError, ValueError) as exc:
        print(f"report failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    try:
        entry = changelog_entry(metrics, previous, registry)
    except ValueError as exc:
        print(f"report failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
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
