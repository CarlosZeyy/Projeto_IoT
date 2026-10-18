"""PT-BR presentation: labels, numbers, time zone and CSV (SPEC-013 sections 4.5 and 4.7).

Dates travel in UTC; they are converted to ``America/Sao_Paulo`` only here, for display. Numbers
use the decimal comma. Enum labels come from ``qc_contracts`` (ADR-012); ``None`` is shown as
``—`` on screen and as an empty field in the CSV.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from zoneinfo import ZoneInfo

from qc_contracts import (
    GRADE_LABELS_PT,
    OBJECT_TYPE_LABELS_PT,
    SOURCE_LABELS_PT,
    Grade,
    InspectionRead,
    ObjectType,
    Source,
    SpcResponse,
)

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
EMPTY = "—"
YES = "Sim"
NO = "Não"
DATETIME_FORMAT = "%d/%m/%Y %H:%M"

HISTORY_COLUMNS: tuple[str, ...] = (
    "Data/hora",
    "Lote",
    "Dispositivo",
    "Tipo",
    "Grau",
    "Nota de grau",
    "Conf. tipo",
    "Conf. grau",
    "Revisão",
    "Defeituosa",
    "Origem",
    "Modelo",
)

CSV_ENCODING = "utf-8-sig"
CSV_DELIMITER = ";"


def _swap_separators(text: str) -> str:
    """``1,234.5`` (Python) -> ``1.234,5`` (PT-BR)."""
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_int(value: int | None) -> str:
    """``1200`` -> ``1.200``; ``None`` -> ``—``."""
    if value is None:
        return EMPTY
    return _swap_separators(f"{value:,}")


def fmt_decimal(value: float | None, places: int = 2) -> str:
    """Rounded to ``places`` with a decimal comma: ``1.8456`` -> ``1,85``; ``None`` -> ``—``."""
    if value is None:
        return EMPTY
    return _swap_separators(f"{value:,.{places}f}")


def fmt_pct(value: float | None, places: int = 1) -> str:
    """Fraction as a percentage: ``0.125`` -> ``12,5%``; ``None`` -> ``—``."""
    if value is None:
        return EMPTY
    return f"{fmt_decimal(value * 100, places)}%"


def fmt_quantized(value: float | None, places: int, rounding: str) -> str:
    """``places`` decimals with a decimal comma, from ``Decimal(repr(value))`` and ``rounding``.

    ``rounding`` is a ``decimal`` mode (``ROUND_FLOOR`` or ``ROUND_CEILING`` for the metrics
    display rule, ``docs/architecture.md`` §7). ``None`` -> ``—``.
    """
    if value is None:
        return EMPTY
    quantum = Decimal(1).scaleb(-places)
    quantized = Decimal(repr(float(value))).quantize(quantum, rounding=rounding)
    return _swap_separators(f"{quantized:,f}")


def fmt_truncated(value: float | None, places: int = 4) -> str:
    """``places`` decimals, never rounded up (``ROUND_FLOOR``): ``0.95999`` -> ``0,9599``.

    ``None`` -> ``—``.
    """
    return fmt_quantized(value, places, ROUND_FLOOR)


def fmt_rounded_up(value: float | None, places: int = 4) -> str:
    """``places`` decimals, never rounded down (``ROUND_CEILING``): ``0.12341`` -> ``0,1235``.

    ``None`` -> ``—``.
    """
    return fmt_quantized(value, places, ROUND_CEILING)


def fmt_bool(value: bool | None) -> str:
    if value is None:
        return EMPTY
    return YES if value else NO


def to_local(value: datetime) -> datetime:
    """The same instant in ``America/Sao_Paulo`` (a naive value is taken as UTC)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(LOCAL_TZ)


def fmt_datetime(value: datetime | None) -> str:
    """Local ``dd/mm/aaaa HH:MM``; ``None`` -> ``—``."""
    if value is None:
        return EMPTY
    return to_local(value).strftime(DATETIME_FORMAT)


def grade_label(grade: Grade | str | None) -> str:
    return EMPTY if grade is None else GRADE_LABELS_PT[Grade(grade)]


def object_type_label(object_type: ObjectType | str | None) -> str:
    return EMPTY if object_type is None else OBJECT_TYPE_LABELS_PT[ObjectType(object_type)]


def source_label(source: Source | str | None) -> str:
    return EMPTY if source is None else SOURCE_LABELS_PT[Source(source)]


def history_rows(items: Iterable[InspectionRead]) -> list[dict[str, str]]:
    """Rows of the history table, with the columns of ``HISTORY_COLUMNS``, as display text."""
    return [
        {
            "Data/hora": fmt_datetime(item.inspected_at),
            "Lote": item.lot_id,
            "Dispositivo": item.device_id,
            "Tipo": object_type_label(item.object_type),
            "Grau": grade_label(item.grade),
            "Nota de grau": fmt_decimal(item.grade_score, 2),
            "Conf. tipo": fmt_decimal(item.type_confidence, 3),
            "Conf. grau": fmt_decimal(item.grade_confidence, 3),
            "Revisão": fmt_bool(item.needs_review),
            "Defeituosa": fmt_bool(item.is_defective),
            "Origem": source_label(item.source),
            "Modelo": item.model_version,
        }
        for item in items
    ]


SPC_COLUMNS: tuple[str, ...] = (
    "Lote",
    "Início",
    "Fim",
    "n",
    "Defeituosas",
    "p",
    "LC",
    "LSC",
    "LIC",
    "Fora de controle",
)


def spc_rows(spc: SpcResponse) -> list[dict[str, str]]:
    """Rows of the p chart table (one per point, columns of ``SPC_COLUMNS``), as display text."""
    return [
        {
            "Lote": point.lot_id,
            "Início": fmt_datetime(point.started_at),
            "Fim": fmt_datetime(point.ended_at),
            "n": fmt_int(point.n),
            "Defeituosas": fmt_int(point.defects),
            "p": fmt_pct(point.p),
            "LC": fmt_pct(point.cl),
            "LSC": fmt_pct(point.ucl),
            "LIC": fmt_pct(point.lcl),
            "Fora de controle": fmt_bool(point.out_of_control),
        }
        for point in spc.points
    ]


def _csv_number(value: float | None) -> str:
    """Exact value, decimal comma, no exponent: ``0.875`` -> ``0,875``; ``None`` -> ``""``."""
    if value is None:
        return ""
    return format(Decimal(repr(float(value))), "f").replace(".", ",")


def _csv_text(value: str) -> str:
    return "" if value == EMPTY else value


def history_csv(items: Sequence[InspectionRead]) -> bytes:
    """CSV of the history page: ``utf-8-sig``, ``;``, decimal comma, ISO 8601 local time."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=CSV_DELIMITER, lineterminator="\n")
    writer.writerow(HISTORY_COLUMNS)
    for item in items:
        writer.writerow(
            [
                to_local(item.inspected_at).isoformat(timespec="seconds"),
                item.lot_id,
                item.device_id,
                _csv_text(object_type_label(item.object_type)),
                _csv_text(grade_label(item.grade)),
                _csv_number(item.grade_score),
                _csv_number(item.type_confidence),
                _csv_number(item.grade_confidence),
                fmt_bool(item.needs_review),
                fmt_bool(item.is_defective),
                _csv_text(source_label(item.source)),
                item.model_version,
            ]
        )
    return buffer.getvalue().encode(CSV_ENCODING)
