"""``qc_dashboard.formatting``: PT-BR numbers, time zone, rows and CSV (SPEC-013 §4.5, §4.7)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

import pytest

from qc_dashboard import formatting as fm


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.125, "12,5%"), (0.0, "0,0%"), (1.0, "100,0%"), (0.33333, "33,3%"), (None, "—")],
)
def test_fmt_pct(value, expected) -> None:
    assert fm.fmt_pct(value) == expected


def test_fmt_numbers() -> None:
    assert fm.fmt_int(40) == "40"
    assert fm.fmt_int(1200) == "1.200"
    assert fm.fmt_int(None) == "—"
    assert fm.fmt_decimal(1.8456, 2) == "1,85"
    assert fm.fmt_decimal(1234.5, 1) == "1.234,5"
    assert fm.fmt_decimal(None) == "—"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.7, "0,7000"),
        (0.96, "0,9600"),
        (0.95999, "0,9599"),
        (0.93127, "0,9312"),
        (1.0, "1,0000"),
        (123.45678, "123,4567"),
        (None, "—"),
    ],
)
def test_fmt_truncated_never_rounds_up(value, expected) -> None:
    assert fm.fmt_truncated(value) == expected


def test_to_local_and_fmt_datetime() -> None:
    moment = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
    local = fm.to_local(moment)
    assert local.utcoffset().total_seconds() == -3 * 3600
    assert local.hour == 12
    assert fm.fmt_datetime(moment) == "03/11/2026 12:00"
    assert fm.fmt_datetime(datetime(2026, 11, 3, 15, 0)) == "03/11/2026 12:00"
    assert fm.fmt_datetime(None) == "—"


def test_labels_come_from_contracts() -> None:
    assert fm.grade_label("unusable") == "inutilizável"
    assert fm.grade_label(None) == "—"
    assert fm.object_type_label("unknown") == "desconhecido"
    assert fm.source_label("simulated") == "simulado"
    assert fm.fmt_bool(True) == "Sim"
    assert fm.fmt_bool(False) == "Não"


def test_history_rows_columns_and_unknown_item(factory) -> None:
    item = factory.inspection(
        object_type="unknown",
        grade=None,
        grade_score=None,
        grade_confidence=None,
        source="simulated",
        needs_review=True,
    )
    (row,) = fm.history_rows([item])
    assert tuple(row) == fm.HISTORY_COLUMNS
    assert row["Data/hora"] == "03/11/2026 12:00"
    assert row["Tipo"] == "desconhecido"
    assert row["Grau"] == "—"
    assert row["Nota de grau"] == "—"
    assert row["Conf. tipo"] == "0,875"
    assert row["Conf. grau"] == "—"
    assert row["Revisão"] == "Sim"
    assert row["Defeituosa"] == "Não"
    assert row["Origem"] == "simulado"
    assert row["Modelo"] == "partqc-mnv3-v1"


def test_history_csv(factory) -> None:
    items = [
        factory.inspection(type_confidence=0.875),
        factory.inspection(
            object_type="unknown",
            grade=None,
            grade_score=None,
            grade_confidence=None,
            type_confidence=0.00001,
        ),
    ]
    payload = fm.history_csv(items)

    assert payload.startswith(b"\xef\xbb\xbf")
    text = payload.decode("utf-8-sig")
    lines = text.splitlines()
    assert lines[0] == ";".join(fm.HISTORY_COLUMNS)
    assert len(lines) == 3
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    first, second = rows[1], rows[2]
    assert first[0] == "2026-11-03T12:00:00-03:00"
    assert first[4] == "bom"
    assert first[5] == "1,25"
    assert first[6] == "0,875"
    assert first[7] == "0,7"
    assert second[3] == "desconhecido"
    assert second[4] == ""
    assert second[5] == ""
    assert second[6] == "0,00001"
    assert second[7] == ""
    assert "—" not in text


def test_spc_rows(factory) -> None:
    rows = fm.spc_rows(factory.spc_response())
    assert len(rows) == 4
    assert tuple(rows[0]) == fm.SPC_COLUMNS
    assert [row["Fora de controle"] for row in rows] == ["Não", "Não", "Sim", "Não"]
    assert rows[0]["p"] == "16,0%"
    assert rows[0]["Início"] == "03/11/2026 12:00"


# ---------- SPEC-028 §4.4: rounding direction ----------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.12341, "0,1235"),
        (0.12340, "0,1234"),
        (0.02, "0,0200"),
        (120.00001, "120,0001"),
        (0.30000000000000004, "0,3001"),
        (1.0, "1,0000"),
        (0.0, "0,0000"),
        (None, "—"),
    ],
)
def test_fmt_rounded_up_never_rounds_down(value, expected) -> None:
    assert fm.fmt_rounded_up(value) == expected


def test_fmt_quantized_modes() -> None:
    from decimal import ROUND_CEILING, ROUND_FLOOR

    assert fm.fmt_quantized(0.93127, 4, ROUND_FLOOR) == "0,9312"
    assert fm.fmt_quantized(0.93127, 4, ROUND_CEILING) == "0,9313"
    assert fm.fmt_quantized(1234.56789, 2, ROUND_FLOOR) == "1.234,56"
    assert fm.fmt_quantized(None, 4, ROUND_CEILING) == "—"
