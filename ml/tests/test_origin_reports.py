"""Author tests of SPEC-035 sections 4.5, 4.6 and 4.8: data report by origin, ``by_origin`` and
``by_source`` in ``metrics.json``, the ``### Dados`` section, the Release notes and the README.
Synthetic data and the tiny ONNX fixture only (no torch)."""

from __future__ import annotations

import copy
import csv
import json
import re
import shutil
from pathlib import Path

import pytest

from qc_ml import data, evaluate, split, thresholds
from qc_ml import report as report_mod
from qc_ml.config import TrainConfig, load_config
from qc_ml.data import EXTERNAL_SOURCE_COLUMNS, load_manifest
from qc_ml.errors import ConfigError
from qc_ml.evaluate import METRIC_KEYS, split_counts
from qc_ml.synthetic import make_synthetic_dataset

ML = Path(__file__).resolve().parents[1]
TINY_MODEL = ML / "tests" / "fixtures" / "tiny_model"
TINY_VERSION = "partqc-tiny-v1"
SYNTHETIC_LINE = "- `synthetic`: 11 imagens, CC0-1.0. Crédito: Synthetic test images"
SYNTHETIC_NOTES_LINE = (
    SYNTHETIC_LINE + " | Licença: https://creativecommons.org/publicdomain/zero/1.0/"
    " | Fonte: https://example.org/synthetic"
)
FOOTER = (
    "Registro das fontes: `ml/external_sources.csv`. Histórico do modelo: `ml/models/CHANGELOG.md`."
)


# ---------- CA-11: data report ----------


def test_ca11_data_report(tmp_path: Path) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=20,
        images_per_item=3,
        contributor_items_per_stratum=1,
        external_items_per_stratum=2,
    )
    registry = root / "external_sources.csv"
    splits = tmp_path / "splits"
    args = ["--dataset-dir", str(root), "--external-sources", str(registry)]
    assert split.main([*args, "--splits-dir", str(splits)]) == 0
    out = tmp_path / "report.json"
    argv = ["report", *args, "--split", str(splits / "split_v1.csv"), "--out", str(out)]
    assert data.main(argv) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    by_origin = report["counts_by_origin"]
    assert set(by_origin) == {"capture", "contributor", "external"}
    assert (by_origin["capture"]["n_images"], by_origin["capture"]["n_items"]) == (660, 220)
    assert (by_origin["contributor"]["n_images"], by_origin["contributor"]["n_items"]) == (33, 11)
    assert (by_origin["external"]["n_images"], by_origin["external"]["n_items"]) == (22, 22)
    assert by_origin["external"]["by_split"] == {"train": 22, "val": 0, "test": 0}
    assert sum(sum(o["by_split"].values()) for o in by_origin.values()) == report["n_images"]
    assert report["n_contributors"] == 1
    assert report["by_source"] == {"synthetic": 22}
    assert report["items_per_grade"]["screw"]["perfect"] == 21
    assert report["items_per_grade"]["other"]["none"] == 21
    assert len(report["below_target"]) == 10
    assert {(e["n_images"], e["n_items"]) for e in report["below_target"]} == {(63, 21)}
    assert report["below_minimum"] == []
    assert report["external_fraction_train"] == pytest.approx(22 / 517, abs=1e-12)
    assert report["n_images"] == 715 and report["n_items"] == 253
    assert report["counts"]["screw"]["perfect"]["total"] == 65  # all images
    assert report["images_per_item"]["min"] == 3  # the 1-image externals are not counted
    assert "c01" not in out.read_text(encoding="utf-8")


def test_data_report_without_split_or_externals(dataset: Path) -> None:
    report = data.build_data_report(load_manifest(dataset))
    assert report["counts_by_origin"] == {
        "capture": {"n_images": 88, "n_items": 44, "by_split": {}},
        "contributor": {"n_images": 0, "n_items": 0, "by_split": {}},
        "external": {"n_images": 0, "n_items": 0, "by_split": {}},
    }
    assert report["n_contributors"] == 0
    assert report["by_source"] == {}
    assert report["external_fraction_train"] is None


# ---------- CA-12: metrics.json ----------


@pytest.fixture(scope="module")
def _evaluated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Dataset 4/2 with one external item per stratum, split, thresholds and evaluate."""
    base = tmp_path_factory.mktemp("evaluated")
    root = make_synthetic_dataset(base / "ds", external_items_per_stratum=1)
    registry = root / "external_sources.csv"
    splits = base / "splits"
    argv = ["--dataset-dir", str(root), "--splits-dir", str(splits)]
    assert split.main([*argv, "--external-sources", str(registry)]) == 0
    models = base / "models"
    shutil.copytree(TINY_MODEL, models / TINY_VERSION)
    config = {
        "model_version": TINY_VERSION,
        "dataset_dir": str(root),
        "split_file": str(splits / "split_v1.csv"),
        "backbone": "tiny",
        "pretrained": False,
        "epochs_a": 1,
        "epochs_b_max": 1,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(models),
        "reports_root": str(base / "reports"),
        "checkpoints_root": str(base / "checkpoints"),
        "external_sources": str(registry),
    }
    path = base / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    assert thresholds.main(["--config", str(path)]) == 0
    assert evaluate.main(["--config", str(path), "--latency-machine", "ci"]) == 0
    return base


def _model_copy(evaluated: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(evaluated / "models" / TINY_VERSION, tmp_path / "model"))


def test_ca12_metrics_counts(_evaluated: Path) -> None:
    metrics_path = _evaluated / "models" / TINY_VERSION / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert list(metrics) == list(METRIC_KEYS)
    counts = metrics["counts"]
    assert counts["train"]["by_origin"] == {"capture": 44, "contributor": 0, "external": 11}
    assert counts["val"]["by_origin"]["external"] == 0
    assert counts["test"]["by_origin"]["external"] == 0
    assert counts["train"]["by_source"] == {"synthetic": 11}
    assert counts["val"]["by_source"] == counts["test"]["by_source"] == {}
    assert counts["train"]["n_images"] == 55


def test_ca12_thresholds_fail_without_the_registry(_evaluated: Path, tmp_path: Path) -> None:
    config = json.loads((_evaluated / "config.json").read_text(encoding="utf-8"))
    config["external_sources"] = str(tmp_path / "absent.csv")
    config["models_root"] = str(tmp_path / "models")
    shutil.copytree(TINY_MODEL, tmp_path / "models" / TINY_VERSION)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    assert thresholds.main(["--config", str(path)]) == 2  # unknown_source_id
    assert not (tmp_path / "models" / TINY_VERSION / "metrics.json").exists()


def test_split_counts_without_origin_columns(dataset: Path) -> None:
    df = load_manifest(dataset).drop(columns=["origin", "contributor", "source_id"])
    counts = split_counts(df, data.DEFAULT_LABELS)
    assert counts["by_origin"] == {"capture": 88, "contributor": 0, "external": 0}
    assert counts["by_source"] == {}


# ---------- config ----------


def test_config_external_sources_field(tmp_path: Path) -> None:
    base = {"model_version": "partqc-mnv3-v1", "dataset_dir": "d", "split_file": "s"}
    assert TrainConfig(**base).external_sources is None
    config = TrainConfig(**base, external_sources="ml/external_sources.csv")
    assert config.external_sources == "ml/external_sources.csv"
    assert config.deviations_from_defaults == []
    for bad in (3, ""):
        with pytest.raises(ConfigError, match="external_sources"):
            TrainConfig(**base, external_sources=bad)
    path = tmp_path / "c.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    assert load_config(path).external_sources is None
    repo = load_config(ML / "configs" / "partqc-mnv3-v1.json")
    assert repo.external_sources is None


# ---------- CA-13: CHANGELOG ----------


def _changelog(model_dir: Path, registry: Path, capsys) -> tuple[int, str]:
    capsys.readouterr()
    code = report_mod.main(
        ["changelog", "--model-dir", str(model_dir), "--external-sources", str(registry)]
    )
    return code, capsys.readouterr().out


def _source_lines(text: str) -> list[str]:
    """Lines starting with ``- ` `` (in a CHANGELOG entry, only those of ``### Dados``)."""
    lines = text.splitlines()
    if "### Dados" in lines:
        start = lines.index("### Dados")
        end = lines.index("### O que mudou")
        lines = lines[start:end]
    return [line for line in lines if line.startswith("- `")]


def _header_only(tmp_path: Path) -> Path:
    path = tmp_path / "header_only.csv"
    path.write_text(",".join(EXTERNAL_SOURCE_COLUMNS) + "\n", encoding="utf-8")
    return path


def test_ca13_changelog_data_section(_evaluated: Path, tmp_path: Path, capsys) -> None:
    model = _model_copy(_evaluated, tmp_path)
    registry = _evaluated / "ds" / "external_sources.csv"
    code, out = _changelog(model, registry, capsys)
    assert code == 0
    lines = out.splitlines()
    assert "### Dados" in lines
    assert "- Validação e teste: 0 e 0 imagens externas (ADR-020)." in lines
    assert "- Treino: 11 imagens externas de 55 (0,2000)." in lines
    assert SYNTHETIC_LINE in lines
    table_end = max(i for i, line in enumerate(lines) if line.startswith("| `"))
    assert table_end < lines.index("### Dados") < lines.index("### O que mudou")
    code, out = _changelog(model, _header_only(tmp_path), capsys)
    assert code == 0
    assert _source_lines(out) == ["- `synthetic`: 11 imagens, licença não encontrada no registro"]
    metrics = json.loads((model / "metrics.json").read_text(encoding="utf-8"))
    for name in ("train", "val", "test"):
        del metrics["counts"][name]["by_origin"]
        del metrics["counts"][name]["by_source"]
    (model / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    code, out = _changelog(model, registry, capsys)
    assert code == 0 and "### Dados" not in out


@pytest.mark.parametrize(
    ("external", "n_train", "shown"),
    [(1, 3, "0,3334"), (0, 10, "0,0000"), (1, 1, "1,0000"), (2, 0, "—")],
)
def test_data_section_fraction_rounds_up(external: int, n_train: int, shown: str) -> None:
    metrics = {
        "counts": {
            "train": {"n_images": n_train, "by_origin": {"external": external}, "by_source": {}},
            "val": {"by_origin": {"external": 0}},
            "test": {"by_origin": {"external": 0}},
        }
    }
    lines = report_mod.data_section(metrics, {})
    assert f"- Treino: {external} imagens externas de {n_train} ({shown})." in lines


def test_changelog_registry_problem_fails(_evaluated: Path, tmp_path: Path, capsys) -> None:
    model = _model_copy(_evaluated, tmp_path)
    registry = _registry_with(_evaluated, tmp_path, license="CC-BY-NC-4.0")
    capsys.readouterr()
    argv = ["changelog", "--model-dir", str(model), "--external-sources", str(registry)]
    assert report_mod.main(argv) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "invalid_license" in captured.err


# ---------- CA-16 to CA-19: Release notes ----------


def _registry_with(evaluated: Path, tmp_path: Path, extra: list[str] | None = None, **edit) -> Path:
    source = dict(
        zip(
            EXTERNAL_SOURCE_COLUMNS,
            [
                "synthetic",
                "Synthetic dataset",
                "https://example.org/synthetic",
                "CC0-1.0",
                "https://creativecommons.org/publicdomain/zero/1.0/",
                "Synthetic test images",
                "2026-10-20",
            ],
            strict=True,
        )
    )
    source.update(edit)
    path = tmp_path / "registry.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(EXTERNAL_SOURCE_COLUMNS)
        writer.writerow([source[c] for c in EXTERNAL_SOURCE_COLUMNS])
        if extra:
            writer.writerow(extra)
    return path


def _notes(model: Path, registry: Path, capsys, output: Path | None = None) -> tuple[int, str, str]:
    capsys.readouterr()
    argv = ["release-notes", "--model-dir", str(model), "--external-sources", str(registry)]
    if output is not None:
        argv += ["--output", str(output)]
    code = report_mod.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _edit_metrics(model: Path, edit) -> None:
    metrics = json.loads((model / "metrics.json").read_text(encoding="utf-8"))
    edit(metrics)
    (model / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")


def test_ca16_release_notes(_evaluated: Path, tmp_path: Path, capsys) -> None:
    model = _model_copy(_evaluated, tmp_path)
    registry = _evaluated / "ds" / "external_sources.csv"
    output = tmp_path / "notes.md"
    code, out, _ = _notes(model, registry, capsys, output)
    assert code == 0 and out == ""
    data_bytes = output.read_bytes()
    text = data_bytes.decode("utf-8")
    assert not data_bytes.startswith(b"\xef\xbb\xbf")
    assert text.endswith("\n") and not text.endswith("\n\n") and "\r" not in text
    sha = (model / "model.sha256").read_text(encoding="ascii").rstrip("\n")
    assert text == (
        f"sha256: {sha}\n\n## Fontes externas e créditos\n\n{SYNTHETIC_NOTES_LINE}\n\n{FOOTER}\n"
    )
    assert "não usa imagens externas" not in text
    _, changelog = _changelog(model, registry, capsys)
    assert _source_lines(text)[0].startswith(_source_lines(changelog)[0])
    code, out, _ = _notes(model, registry, capsys)
    assert code == 0 and out.encode("utf-8") == data_bytes


def test_ca16_stdout_bytes_in_subprocess(_evaluated: Path, tmp_path: Path) -> None:
    import subprocess
    import sys

    model = _model_copy(_evaluated, tmp_path)
    registry = _evaluated / "ds" / "external_sources.csv"
    argv = [sys.executable, "-m", "qc_ml.report", "release-notes", "--model-dir", str(model)]
    argv += ["--external-sources", str(registry)]
    result = subprocess.run(argv, capture_output=True, env={"PATH": "", "LC_ALL": "C"})
    assert result.returncode == 0, result.stderr
    output = tmp_path / "notes.md"
    assert report_mod.main([*argv[3:], "--output", str(output)]) == 0
    assert result.stdout == output.read_bytes()


def test_ca17_source_not_in_registry_blocks(_evaluated: Path, tmp_path: Path, capsys) -> None:
    model = _model_copy(_evaluated, tmp_path)
    registry = _evaluated / "ds" / "external_sources.csv"
    _edit_metrics(
        model, lambda m: m["counts"]["train"].update(by_source={"zz-fora": 2, "synthetic": 11})
    )
    output = tmp_path / "notes.md"
    for existing in (None, "antigo\n"):
        if existing is not None:
            output.write_text(existing, encoding="utf-8")
        code, out, err = _notes(model, registry, capsys, output)
        assert code == 2 and out == ""
        assert "source not in registry: zz-fora" in err
        assert "source not in registry: synthetic" not in err
        if existing is None:
            assert not output.exists()
        else:
            assert output.read_text(encoding="utf-8") == "antigo\n"
    code, changelog = _changelog(model, registry, capsys)
    assert code == 0
    assert "- `zz-fora`: 2 imagens, licença não encontrada no registro" in changelog.splitlines()


def test_ca17_header_only_registry_blocks(_evaluated: Path, tmp_path: Path, capsys) -> None:
    model = _model_copy(_evaluated, tmp_path)
    code, out, err = _notes(model, _header_only(tmp_path), capsys)
    assert code == 2 and out == ""
    assert "source not in registry: synthetic" in err.splitlines()


def test_ca17_invalid_source_id_is_not_echoed(_evaluated: Path, tmp_path: Path, capsys) -> None:
    model = _model_copy(_evaluated, tmp_path)
    marker = "MARK" + "x9q7"
    bad = f"bad{marker}‮"
    _edit_metrics(model, lambda m: m["counts"]["train"].update(by_source={bad: 1, "synthetic": 11}))
    code, out, err = _notes(model, _evaluated / "ds" / "external_sources.csv", capsys)
    assert code == 2 and out == ""
    assert "source not in registry: <invalid source_id>" in err
    assert marker not in err and "‮" not in err
    code, changelog = _changelog(model, _evaluated / "ds" / "external_sources.csv", capsys)
    assert code == 0 and marker not in changelog


def test_ca17_order_of_two_sources(_evaluated: Path, tmp_path: Path, capsys) -> None:
    model = _model_copy(_evaluated, tmp_path)
    extra = [
        "aa-fonte",
        "Fonte AA",
        "https://example.org/aa",
        "CC-BY-4.0",
        "https://creativecommons.org/licenses/by/4.0/",
        "Fonte AA",
        "2026-10-21",
    ]
    registry = _registry_with(_evaluated, tmp_path, extra=extra)
    _edit_metrics(
        model, lambda m: m["counts"]["train"].update(by_source={"synthetic": 11, "aa-fonte": 2})
    )
    code, out, _ = _notes(model, registry, capsys)
    assert code == 0
    lines = _source_lines(out)
    assert lines == [
        "- `aa-fonte`: 2 imagens, CC-BY-4.0. Crédito: Fonte AA | Licença: "
        "https://creativecommons.org/licenses/by/4.0/ | Fonte: https://example.org/aa",
        SYNTHETIC_NOTES_LINE,
    ]
    _, changelog = _changelog(model, registry, capsys)
    for note, entry in zip(lines, _source_lines(changelog), strict=True):
        assert note.startswith(entry)


def _no_externals(metrics: dict) -> None:
    for name in ("train", "val", "test"):
        metrics["counts"][name]["by_source"] = {}
        metrics["counts"][name]["by_origin"]["external"] = 0


def _before_spec(metrics: dict) -> None:
    for name in ("train", "val", "test"):
        del metrics["counts"][name]["by_source"]
        del metrics["counts"][name]["by_origin"]


@pytest.mark.parametrize("edit", [_no_externals, _before_spec], ids=["empty", "old-metrics"])
def test_ca18_release_notes_without_externals(
    _evaluated: Path, tmp_path: Path, capsys, edit
) -> None:
    model = _model_copy(_evaluated, tmp_path)
    _edit_metrics(model, edit)
    code, out, _ = _notes(model, _evaluated / "ds" / "external_sources.csv", capsys)
    assert code == 0
    sha = (model / "model.sha256").read_text(encoding="ascii").rstrip("\n")
    assert out == (
        f"sha256: {sha}\n\n## Fontes externas e créditos\n\n"
        f"Este modelo não usa imagens externas (ADR-020).\n\n{FOOTER}\n"
    )
    assert _source_lines(out) == []


def _remove_sha(model: Path) -> None:
    (model / "model.sha256").unlink()


def _short_sha(model: Path) -> None:
    (model / "model.sha256").write_text("a" * 63 + "\n", encoding="ascii")


def _remove_metrics(model: Path) -> None:
    (model / "metrics.json").unlink()


def _broken_metrics(model: Path) -> None:
    (model / "metrics.json").write_text("{not json", encoding="utf-8")


def _list_metrics(model: Path) -> None:
    (model / "metrics.json").write_text("[]", encoding="utf-8")


def _bad_by_source(model: Path) -> None:
    _edit_metrics(model, lambda m: m["counts"]["train"].update(by_source=["synthetic"]))


@pytest.mark.parametrize(
    "breakage",
    [
        _remove_sha,
        _short_sha,
        _remove_metrics,
        _broken_metrics,
        _list_metrics,
        _bad_by_source,
        None,
    ],
)
def test_ca19_release_notes_errors(_evaluated: Path, tmp_path: Path, capsys, breakage) -> None:
    model = _model_copy(_evaluated, tmp_path)
    registry = _evaluated / "ds" / "external_sources.csv"
    if breakage is None:  # registry with a refused licence
        registry = _registry_with(_evaluated, tmp_path, license="CC-BY-NC-4.0")
    else:
        breakage(model)
    output = tmp_path / "out" / "notes.md"
    output.parent.mkdir()
    code, out, err = _notes(model, registry, capsys, output)
    assert code == 2 and out == "" and err
    assert not output.exists()
    output.write_text("antigo\n", encoding="utf-8")
    code, out, _ = _notes(model, registry, capsys, output)
    assert code == 2 and out == ""
    assert output.read_text(encoding="utf-8") == "antigo\n"
    assert sorted(p.name for p in output.parent.iterdir()) == ["notes.md"]


def test_release_notes_default_registry(_evaluated: Path, tmp_path: Path, capsys) -> None:
    model = _model_copy(_evaluated, tmp_path)
    capsys.readouterr()
    # the registry of the repository has no lines: the synthetic source is not in it
    assert report_mod.main(["release-notes", "--model-dir", str(model)]) == 2
    assert "source not in registry: synthetic" in capsys.readouterr().err


def test_release_notes_function_is_pure() -> None:
    metrics = {"counts": {"train": {"by_source": {}}}}
    before = copy.deepcopy(metrics)
    text = report_mod.release_notes("a" * 64, metrics, {})
    assert metrics == before
    assert text.splitlines()[0] == "sha256: " + "a" * 64


# ---------- CA-20: README ----------


def _readme_section(title: str) -> str:
    lines = (ML / "README.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("#") and title in line)
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(rf"#{{1,{level}}} ", lines[i])),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_ca20_readme_section() -> None:
    section = _readme_section("Origem das imagens")
    for needle in (
        "ml/external_sources.csv",
        "--max-external-fraction",
        "qc_ml.report release-notes",
        "--notes-file",
        "source not in registry",
        "docs/dataset-protocol.md",
        "sources.csv",
        "XS-0001",
    ):
        assert needle in section, needle
    release = _readme_section("Do Colab ao Release")
    assert '--notes "sha256' not in release
    assert "Origem das imagens" in release
