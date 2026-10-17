"""``metrics.json`` of the model and the PRD targets (SPEC-013 section 4.6).

The file format is the one of SPEC-012 section 4.7. The dashboard cannot import ``qc_ml`` (it
brings the inference runtime, R-12), so ``PRD_TARGETS`` repeats the targets of SPEC-012 and of
the PRD (section 7): a change of a target must be made in both places.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from qc_contracts import GRADE_ORDER, MODEL_VERSION_PATTERN
from qc_dashboard.config import resolve_repo_path
from qc_dashboard.formatting import (
    EMPTY,
    fmt_datetime,
    fmt_int,
    fmt_truncated,
    grade_label,
)

# Top-level keys of metrics.json, exactly as in SPEC-012 section 4.7.
REQUIRED_KEYS: tuple[str, ...] = (
    "model_version",
    "model_sha256",
    "evaluated_at",
    "split_file",
    "split_sha256",
    "manifest_sha256",
    "labels",
    "decision",
    "type_accuracy",
    "type_confusion",
    "grade_qwk",
    "grade_mae",
    "grade_off_by_one_accuracy",
    "grade_confusion",
    "grade_per_class",
    "unusable_recall",
    "unusable_precision",
    "defective_recall",
    "defective_precision",
    "unknown_rate_on_other",
    "false_unknown_rate",
    "needs_review_rate",
    "latency_ms_p50",
    "latency_ms_p95",
    "latency_machine",
    "latency_runs",
    "counts",
    "grade_qwk_ci95",
    "unusable_recall_ci95",
    "defective_recall_ci95",
    "n_items_test_by_grade",
    "warnings",
)

STATUS_MET = "Atingida"
STATUS_BELOW = "Abaixo da meta"
STATUS_UNKNOWN = EMPTY

CONFUSION_IMAGES: tuple[str, ...] = ("type_confusion.png", "grade_confusion.png")
REPORTS_DIR = "ml/reports"


class MetricsFileError(ValueError):
    """``metrics.json`` is not valid JSON or lacks a required key. The message is PT-BR."""


@dataclass(frozen=True)
class Target:
    key: str
    label: str
    op: Literal[">=", "<="]
    threshold: float

    def describe(self) -> str:
        symbol = "≥" if self.op == ">=" else "≤"
        threshold = f"{self.threshold:g}".replace(".", ",")
        return f"{symbol} {threshold}"

    def status(self, value: Any) -> str:
        if not _is_number(value):
            return STATUS_UNKNOWN
        met = value >= self.threshold if self.op == ">=" else value <= self.threshold
        return STATUS_MET if met else STATUS_BELOW


PRD_TARGETS: tuple[Target, ...] = (
    Target("type_accuracy", "Acurácia de tipo", ">=", 0.95),
    Target("grade_qwk", "QWK do grau", ">=", 0.75),
    Target("grade_off_by_one_accuracy", "Acurácia do grau (±1)", ">=", 0.90),
    Target("unusable_recall", "Recall de inutilizável", ">=", 0.90),
    Target("defective_recall", "Recall de defeituosa", ">=", 0.90),
    Target("latency_ms_p95", "Latência p95 (ms)", "<=", 300),
)

# Metrics without a PRD target, shown after the target table.
OTHER_METRICS: tuple[tuple[str, str], ...] = (
    ("grade_mae", "Erro absoluto médio do grau"),
    ("grade_qwk_ci95", "IC 95% do QWK do grau"),
    ("unusable_precision", "Precisão de inutilizável"),
    ("unusable_recall_ci95", "IC 95% do recall de inutilizável"),
    ("defective_precision", "Precisão de defeituosa"),
    ("defective_recall_ci95", "IC 95% do recall de defeituosa"),
    ("unknown_rate_on_other", "Taxa de desconhecido em outros objetos"),
    ("false_unknown_rate", "Taxa de falso desconhecido"),
    ("needs_review_rate", "Taxa de revisão"),
    ("latency_ms_p50", "Latência p50 (ms)"),
    ("latency_runs", "Medições de latência"),
    ("latency_machine", "Máquina da medição de latência"),
)

GRADE_TABLE_COLUMNS: tuple[str, ...] = (
    "Grau",
    "Precisão",
    "Recall",
    "F1",
    "Suporte (imagens)",
    "Itens no teste",
)


def _is_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isfinite(value)


def load_metrics(path: str | Path) -> dict[str, Any]:
    """Read ``metrics.json`` and check its top-level keys (SPEC-012 section 4.7).

    Raises ``FileNotFoundError`` when the file does not exist and ``MetricsFileError`` (with a
    PT-BR reason) for invalid JSON, a non-object document or missing keys.
    """
    file = Path(path)
    if not file.is_file():
        raise FileNotFoundError(str(file))
    try:
        document = json.loads(file.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise MetricsFileError("o arquivo não está em UTF-8") from None
    except json.JSONDecodeError as exc:
        raise MetricsFileError(
            f"JSON malformado (linha {exc.lineno}, coluna {exc.colno})"
        ) from None
    if not isinstance(document, dict):
        raise MetricsFileError("o conteúdo não é um objeto JSON")
    missing = [key for key in REQUIRED_KEYS if key not in document]
    if missing:
        raise MetricsFileError(f"chaves ausentes: {', '.join(missing)}")
    return document


def fmt_metric(value: Any) -> str:
    """4 decimals, decimal comma, never rounded up; intervals as ``[low; high]``."""
    if _is_number(value):
        return fmt_truncated(value, 4)
    if isinstance(value, list | tuple) and len(value) == 2 and all(_is_number(v) for v in value):
        return f"[{fmt_truncated(value[0], 4)}; {fmt_truncated(value[1], 4)}]"
    if value is None:
        return EMPTY
    return str(value)


def target_rows(metrics: Mapping[str, Any]) -> list[dict[str, str]]:
    """One row per PRD target: metric, value, target and status."""
    return [
        {
            "Métrica": target.label,
            "Valor": fmt_metric(metrics.get(target.key)),
            "Meta": target.describe(),
            "Status": target.status(metrics.get(target.key)),
        }
        for target in PRD_TARGETS
    ]


def other_metric_rows(metrics: Mapping[str, Any]) -> list[dict[str, str]]:
    """The metrics without a target."""
    rows = []
    for key, label in OTHER_METRICS:
        value = metrics.get(key)
        text = fmt_int(value) if key == "latency_runs" and isinstance(value, int) else None
        rows.append({"Métrica": label, "Valor": text or fmt_metric(value)})
    return rows


def grade_rows(metrics: Mapping[str, Any]) -> list[dict[str, str]]:
    """Always the 5 grades, perfeito -> inutilizável; a missing value is ``—``."""
    per_class = metrics.get("grade_per_class")
    items = metrics.get("n_items_test_by_grade")
    per_class = per_class if isinstance(per_class, Mapping) else {}
    items = items if isinstance(items, Mapping) else {}
    rows = []
    for grade in GRADE_ORDER:
        stats = per_class.get(grade.value)
        stats = stats if isinstance(stats, Mapping) else {}
        support = stats.get("support")
        n_items = items.get(grade.value)
        rows.append(
            {
                "Grau": grade_label(grade),
                "Precisão": fmt_metric(stats.get("precision")),
                "Recall": fmt_metric(stats.get("recall")),
                "F1": fmt_metric(stats.get("f1")),
                "Suporte (imagens)": fmt_int(support) if isinstance(support, int) else EMPTY,
                "Itens no teste": fmt_int(n_items) if isinstance(n_items, int) else EMPTY,
            }
        )
    return rows


def short_sha(value: Any) -> str:
    return str(value)[:12] if value else EMPTY


def fmt_evaluated_at(value: Any) -> str:
    """Evaluation time in local time; the raw text when it is not an ISO 8601 datetime."""
    if not isinstance(value, str) or not value:
        return EMPTY
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    return fmt_datetime(moment)


def report_image(model_version: Any, name: str) -> Path | None:
    """``ml/reports/<model_version>/<name>`` when it exists; ``None`` otherwise.

    ``model_version`` must match the contract pattern, so it cannot point outside the reports.
    """
    if not isinstance(model_version, str) or not re.fullmatch(MODEL_VERSION_PATTERN, model_version):
        return None
    path = resolve_repo_path(REPORTS_DIR) / model_version / name
    return path if path.is_file() else None
