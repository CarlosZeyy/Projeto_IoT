"""``qc_dashboard.model_info``: ``metrics.json`` and the PRD targets (SPEC-013 §4.6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qc_dashboard import config, model_info


def write(tmp_path: Path, content: str | dict) -> Path:
    path = tmp_path / "metrics.json"
    text = content if isinstance(content, str) else json.dumps(content)
    path.write_text(text, encoding="utf-8")
    return path


def test_required_keys_match_spec_012() -> None:
    assert len(model_info.REQUIRED_KEYS) == 32
    assert len(set(model_info.REQUIRED_KEYS)) == 32
    for key in (
        "grade_qwk_ci95",
        "unusable_recall_ci95",
        "defective_recall_ci95",
        "n_items_test_by_grade",
        "warnings",
    ):
        assert key in model_info.REQUIRED_KEYS


def test_load_valid_metrics(tmp_path, factory) -> None:
    document = factory.metrics_document()
    assert model_info.load_metrics(write(tmp_path, document)) == document


def test_load_missing_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        model_info.load_metrics(tmp_path / "nope.json")


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{not json", "JSON malformado"),
        ("[1, 2]", "não é um objeto"),
        ({"x": 1}, "chaves ausentes: model_version"),
    ],
)
def test_load_invalid_metrics(tmp_path, content, reason) -> None:
    with pytest.raises(model_info.MetricsFileError) as info:
        model_info.load_metrics(write(tmp_path, content))
    assert reason in str(info.value)


def test_load_metrics_not_utf8(tmp_path) -> None:
    path = tmp_path / "metrics.json"
    path.write_bytes(b"\xff\xfe{")
    with pytest.raises(model_info.MetricsFileError):
        model_info.load_metrics(path)


def test_target_rows(factory) -> None:
    rows = {row["Métrica"]: row for row in model_info.target_rows(factory.metrics_document())}
    assert rows["Acurácia de tipo"]["Status"] == "Atingida"
    assert rows["Acurácia de tipo"]["Valor"] == "0,9600"
    assert rows["Acurácia de tipo"]["Meta"] == "≥ 0,95"
    assert rows["QWK do grau"]["Status"] == "Abaixo da meta"
    assert rows["QWK do grau"]["Valor"] == "0,7000"
    assert rows["Latência p95 (ms)"]["Meta"] == "≤ 300"
    assert rows["Latência p95 (ms)"]["Status"] == "Atingida"
    assert rows["Recall de defeituosa"]["Status"] == "Abaixo da meta"
    assert rows["Recall de inutilizável"]["Status"] == "Atingida"


def test_target_status_null_and_latency_above() -> None:
    latency = next(t for t in model_info.PRD_TARGETS if t.key == "latency_ms_p95")
    assert latency.status(300) == "Atingida"
    assert latency.status(300.5) == "Abaixo da meta"
    assert latency.status(None) == "—"
    assert latency.status(True) == "—"
    assert latency.status(float("nan")) == "—"


def test_prd_targets_values() -> None:
    assert [(t.key, t.op, t.threshold) for t in model_info.PRD_TARGETS] == [
        ("type_accuracy", ">=", 0.95),
        ("grade_qwk", ">=", 0.75),
        ("grade_off_by_one_accuracy", ">=", 0.90),
        ("unusable_recall", ">=", 0.90),
        ("defective_recall", ">=", 0.90),
        ("latency_ms_p95", "<=", 300),
    ]


def test_fmt_metric() -> None:
    assert model_info.fmt_metric(0.70) == "0,7000"
    assert model_info.fmt_metric([0.6, 0.78]) == "[0,6000; 0,7800]"
    assert model_info.fmt_metric(None) == "—"
    assert model_info.fmt_metric("notebook-borda") == "notebook-borda"


def test_other_metric_rows(factory) -> None:
    document = factory.metrics_document()
    rows = {r["Métrica"]: r["Valor"] for r in model_info.other_metric_rows(document)}
    assert rows["Erro absoluto médio do grau"] == "0,3100"
    assert rows["IC 95% do QWK do grau"] == "[0,6000; 0,7800]"
    assert rows["IC 95% do recall de defeituosa"] == "—"
    assert rows["Medições de latência"] == "100"
    assert rows["Máquina da medição de latência"] == "notebook-borda"


def test_grade_rows_always_five(factory) -> None:
    rows = model_info.grade_rows(factory.metrics_document())
    assert [r["Grau"] for r in rows] == ["perfeito", "bom", "mediano", "ruim", "inutilizável"]
    assert rows[0]["Precisão"] == "0,8000"
    assert rows[0]["Suporte (imagens)"] == "8"
    assert rows[0]["Itens no teste"] == "4"
    empty = model_info.grade_rows(factory.metrics_document(grade_per_class=None))
    assert len(empty) == 5
    assert empty[0]["Recall"] == "—"


def test_header_helpers() -> None:
    assert model_info.short_sha("0123456789abcdef") == "0123456789ab"
    assert model_info.fmt_evaluated_at("2026-11-20T13:30:00+00:00") == "20/11/2026 10:30"
    assert model_info.fmt_evaluated_at("ontem") == "ontem"
    assert model_info.fmt_evaluated_at(None) == "—"


def test_report_image(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    assert model_info.report_image("partqc-test-v0", "type_confusion.png") is None
    folder = tmp_path / "ml" / "reports" / "partqc-test-v0"
    folder.mkdir(parents=True)
    (folder / "type_confusion.png").write_bytes(b"\x89PNG")
    assert model_info.report_image("partqc-test-v0", "type_confusion.png") == (
        folder / "type_confusion.png"
    )
    assert model_info.report_image("../etc", "type_confusion.png") is None
    assert model_info.report_image(None, "type_confusion.png") is None
