"""``qc_dashboard.model_info``: ``metrics.json`` and the PRD targets.

SPEC-013 §4.6 and SPEC-028 §4.4.
"""

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


# ---------- SPEC-028 §4.4: display rule (RV-07) ----------


def test_lower_is_better_list_matches_architecture() -> None:
    assert {
        "grade_mae",
        "false_unknown_rate",
        "needs_review_rate",
        "latency_ms_p50",
        "latency_ms_p95",
    } == model_info.LOWER_IS_BETTER
    targets = {t.key: t.op for t in model_info.PRD_TARGETS}
    # Every "<=" target is a lower-is-better metric, and vice versa for the targets.
    assert {k for k, op in targets.items() if op == "<="} == (
        model_info.LOWER_IS_BETTER & targets.keys()
    )


@pytest.mark.parametrize("key", sorted(model_info.LOWER_IS_BETTER))
def test_lower_is_better_metrics_round_up(key: str) -> None:
    assert model_info.fmt_metric(0.12341, key) == "0,1235"
    assert model_info.fmt_metric(0.1234, key) == "0,1234"


@pytest.mark.parametrize(
    "key", ["type_accuracy", "grade_qwk", "unusable_recall", "unknown_rate_on_other", None]
)
def test_higher_is_better_metrics_round_down(key) -> None:
    assert model_info.fmt_metric(0.93127, key) == "0,9312"


def test_interval_is_never_narrower() -> None:
    assert model_info.fmt_metric([0.61239, 0.78761], "grade_qwk_ci95") == "[0,6123; 0,7877]"
    assert model_info.fmt_metric((0.61239, 0.78761), "grade_mae") == "[0,6123; 0,7877]"
    assert model_info.fmt_metric([0.6, 0.78]) == "[0,6000; 0,7800]"


def test_rows_use_the_direction_of_each_metric(factory) -> None:
    document = factory.metrics_document(
        type_accuracy=0.93127,
        grade_qwk=0.75,
        grade_mae=0.12341,
        latency_ms_p95=120.00001,
        latency_ms_p50=40.00001,
        false_unknown_rate=0.02,
        needs_review_rate=0.10001,
        unusable_precision=0.85559,
        grade_qwk_ci95=[0.61239, 0.78761],
    )
    targets = {row["Métrica"]: row for row in model_info.target_rows(document)}
    assert (targets["Acurácia de tipo"]["Valor"], targets["Acurácia de tipo"]["Status"]) == (
        "0,9312",
        "Abaixo da meta",
    )
    assert (targets["QWK do grau"]["Valor"], targets["QWK do grau"]["Status"]) == (
        "0,7500",
        "Atingida",
    )
    latency = targets["Latência p95 (ms)"]
    assert (latency["Valor"], latency["Status"]) == ("120,0001", "Atingida")
    others = {r["Métrica"]: r["Valor"] for r in model_info.other_metric_rows(document)}
    assert others["Erro absoluto médio do grau"] == "0,1235"
    assert others["Latência p50 (ms)"] == "40,0001"
    assert others["Taxa de falso desconhecido"] == "0,0200"
    assert others["Taxa de revisão"] == "0,1001"
    assert others["Precisão de inutilizável"] == "0,8555"
    assert others["IC 95% do QWK do grau"] == "[0,6123; 0,7877]"
    assert others["Medições de latência"] == "100"


def test_status_uses_the_raw_value() -> None:
    latency = next(t for t in model_info.PRD_TARGETS if t.key == "latency_ms_p95")
    # Shown as 300,0000 after rounding up, but the raw value is above the target.
    assert model_info.fmt_metric(300.00001, "latency_ms_p95") == "300,0001"
    assert latency.status(300.00001) == "Abaixo da meta"
    qwk = next(t for t in model_info.PRD_TARGETS if t.key == "grade_qwk")
    assert model_info.fmt_metric(0.74999, "grade_qwk") == "0,7499"
    assert qwk.status(0.74999) == "Abaixo da meta"


# ---------- SPEC-028 §4.4: path in the message (SEC-13-03) ----------


def test_display_path_relative_inside_the_repository() -> None:
    relative = "ml/models/nao-existe-v0/metrics.json"
    assert model_info.display_path(relative) == relative
    assert model_info.display_path(config.REPO_ROOT / relative) == relative
    assert model_info.display_path("ml/models/../models/x/metrics.json") == (
        "ml/models/x/metrics.json"
    )


def test_display_path_absolute_outside_the_repository(tmp_path) -> None:
    outside = tmp_path / "metrics.json"
    assert model_info.display_path(outside) == str(outside)
    assert model_info.display_path("../fora/metrics.json").startswith("/")


def test_display_path_follows_the_patched_root(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    assert model_info.display_path(tmp_path / "ml" / "m.json") == "ml/m.json"


# ---------- SPEC-028 §4.4: report_image inside ml/reports (SEC-13-08) ----------


def _report(folder: Path, name: str = "type_confusion.png") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    image = folder / name
    image.write_bytes(b"\x89PNG")
    return image


def test_report_image_refuses_links_out_of_reports(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path / "repo")
    reports = tmp_path / "repo" / "ml" / "reports"
    ok = _report(reports / "partqc-ok-v1")
    _report(tmp_path / "outside")
    (reports / "partqc-link-v1").symlink_to(tmp_path / "outside", target_is_directory=True)
    (reports / "partqc-alias-v1").symlink_to(reports / "partqc-ok-v1", target_is_directory=True)

    assert model_info.report_image("partqc-ok-v1", "type_confusion.png") == ok
    assert model_info.report_image("partqc-link-v1", "type_confusion.png") is None
    # A link that stays inside ml/reports is accepted.
    assert model_info.report_image("partqc-alias-v1", "type_confusion.png") is not None
    for version in ("...", "....", "../x", "..", ".", "ab", "Partqc-ok-v1", "partqc-ok-v1\n"):
        assert model_info.report_image(version, "type_confusion.png") is None, version
    assert model_info.report_image("partqc-ok-v1", "grade_confusion.png") is None


def test_report_image_refuses_a_file_link_out_of_reports(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path / "repo")
    folder = tmp_path / "repo" / "ml" / "reports" / "partqc-ok-v1"
    folder.mkdir(parents=True)
    outside = _report(tmp_path / "outside")
    (folder / "type_confusion.png").symlink_to(outside)
    assert model_info.report_image("partqc-ok-v1", "type_confusion.png") is None
