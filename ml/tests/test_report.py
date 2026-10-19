"""Author tests for qc_ml.report (SPEC-012 §4.8; CA-25). No torch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qc_ml import report as report_mod
from qc_ml.report import changelog_entry, format_metric

BASE = {
    "model_version": "partqc-mnv3-v1",
    "model_sha256": "a" * 64,
    "evaluated_at": "2026-11-02T13:00:00+00:00",
    "split_file": "split_v1.csv",
    "split_sha256": "b" * 64,
    "manifest_sha256": "c" * 64,
    "decision": {"type_threshold": 0.7, "unusable_threshold": 0.3, "grade_review_threshold": 0.6},
    "type_accuracy": 0.93127,
    "grade_qwk": 0.75,
    "grade_qwk_ci95": [0.61234, 0.85551],
    "grade_off_by_one_accuracy": None,
    "grade_mae": 0.12341,
    "unusable_recall": 0.9,
    "defective_recall": 0.95,
    "latency_ms_p50": 80.0,
    "latency_ms_p95": 120.00001,
    "latency_runs": 100,
    "latency_machine": "notebook-borda",
    "warnings": [
        "grade fair has 1 item(s) in the test split (< 2): its metrics are very uncertain"
    ],
}


def _row(text: str, key: str) -> list[str]:
    line = next(line for line in text.splitlines() if line.startswith(f"| `{key}`"))
    return [cell.strip() for cell in line.strip("|").split("|")]


def test_ca25_display_rule_and_status() -> None:
    text = changelog_entry(BASE)
    assert text.startswith("## partqc-mnv3-v1 — 2026-11-02\n")
    assert _row(text, "type_accuracy")[1:] == ["0,9312", "≥ 0,95", "abaixo da meta"]
    assert _row(text, "grade_qwk")[1:] == ["0,7500", "≥ 0,75", "atingida"]
    assert _row(text, "latency_ms_p95")[1:] == ["120,0001", "≤ 300", "atingida"]
    assert _row(text, "grade_off_by_one_accuracy")[1:] == ["—", "≥ 0,90", "n/d"]
    assert _row(text, "grade_mae")[1] == "0,1235"
    assert _row(text, "grade_qwk_ci95")[1] == "[0,6123; 0,8556]"
    assert _row(text, "latency_runs")[1] == "100"
    assert "### O que mudou" in text and "### Problemas conhecidos" in text
    assert BASE["warnings"][0] in text


def test_format_metric_edges() -> None:
    assert format_metric(0.95999, "type_accuracy") == "0,9599"
    assert format_metric(0.70) == "0,7000"
    assert format_metric(1, "type_accuracy") == "1,0000"
    assert format_metric(None) == "—"
    assert format_metric(0.04000001, "false_unknown_rate") == "0,0401"


def test_cli_with_previous_and_append(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    current, previous = tmp_path / "v2", tmp_path / "v1"
    current.mkdir()
    previous.mkdir()
    (current / "metrics.json").write_text(json.dumps({**BASE, "model_version": "partqc-mnv3-v2"}))
    (previous / "metrics.json").write_text(json.dumps({**BASE, "type_accuracy": 0.9}))
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Header\n", encoding="utf-8")
    args = ["changelog", "--model-dir", str(current), "--previous", str(previous)]
    assert report_mod.main([*args, "--append", str(changelog)]) == 0
    out = capsys.readouterr().out
    assert "Anterior (partqc-mnv3-v1)" in out
    assert _row(out, "type_accuracy")[1:] == ["0,9312", "≥ 0,95", "abaixo da meta", "0,9000"]
    text = changelog.read_text(encoding="utf-8")
    assert text.startswith("# Header\n\n## partqc-mnv3-v2 — 2026-11-02")


def test_cli_errors(tmp_path: Path) -> None:
    assert report_mod.main(["changelog", "--model-dir", str(tmp_path)]) == 2
    assert report_mod.main([]) == 2


def test_repository_changelog_header_exists() -> None:
    path = Path(__file__).resolve().parents[1] / "models" / "CHANGELOG.md"
    assert path.read_text(encoding="utf-8").startswith("# ")
