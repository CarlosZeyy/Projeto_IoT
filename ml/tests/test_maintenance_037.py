"""Author tests of SPEC-037 (ML maintenance): counts of ``metrics.json`` in the Release notes and
in the CHANGELOG, the ceiling that underflows, the exact header of ``sources.csv`` and of the
registry, the synthetic generator without ``item_id`` collisions and the export ``finally``.

Synthetic data and ``tmp_path`` only; no torch (the slow export test is in
``test_export_warnings.py``)."""

from __future__ import annotations

import argparse
import ast
import copy
import csv
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from qc_ml import data, split
from qc_ml import report as report_mod
from qc_ml.data import (
    EXTERNAL_SOURCE_COLUMNS,
    SOURCE_COLUMNS,
    load_external_sources,
    load_manifest,
    parse_csv,
)
from qc_ml.errors import ManifestError
from qc_ml.synthetic import SYNTHETIC_SOURCE, make_synthetic_dataset

ML = Path(__file__).resolve().parents[1]
SHA = "0123456789abcdef" * 4
NOTES_LINE = (
    "- `synthetic`: 11 imagens, CC0-1.0. Crédito: Synthetic test images | Licença: "
    "https://creativecommons.org/publicdomain/zero/1.0/ | Fonte: https://example.org/synthetic"
)
FORGED = "11 imagens\n- `forged`: 9"
BASE: dict = {
    "model_version": "partqc-test-v1",
    "counts": {
        "train": {
            "n_images": 55,
            "by_origin": {"capture": 44, "contributor": 0, "external": 11},
            "by_source": {"synthetic": 11},
        },
        "val": {
            "n_images": 20,
            "by_origin": {"capture": 20, "contributor": 0, "external": 0},
            "by_source": {},
        },
        "test": {
            "n_images": 22,
            "by_origin": {"capture": 22, "contributor": 0, "external": 0},
            "by_source": {},
        },
    },
}


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _registry(tmp_path: Path) -> Path:
    return _write_csv(
        tmp_path / "external_sources.csv", list(EXTERNAL_SOURCE_COLUMNS), [list(SYNTHETIC_SOURCE)]
    )


def _model_dir(tmp_path: Path, metrics: dict) -> Path:
    model_dir = tmp_path / "model"
    model_dir.mkdir(exist_ok=True)
    (model_dir / "model.sha256").write_text(SHA + "\n", encoding="utf-8")
    (model_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return model_dir


def _base() -> dict:
    return copy.deepcopy(BASE)


# ---------- 4.1: the single count check ----------


@pytest.mark.parametrize("value", [0, 1, 11, 10**30])
def test_valid_counts(value: int) -> None:
    assert report_mod.is_valid_count(value)


@pytest.mark.parametrize(
    "value", [True, False, -1, -3, 1.5, 11.0, None, "11", FORGED, [], {}, float("nan")]
)
def test_invalid_counts(value: object) -> None:
    assert not report_mod.is_valid_count(value)


def test_check_counts_lists_every_field_in_order() -> None:
    metrics = _base()
    metrics["counts"]["train"]["n_images"] = "x"
    metrics["counts"]["train"]["by_source"] = {"b-src": -1, "a-src": 2, "bad id": True}
    del metrics["counts"]["val"]["by_origin"]["external"]
    del metrics["counts"]["test"]
    with pytest.raises(report_mod.InvalidCountsError) as info:
        report_mod.check_counts(metrics, data_section=True)
    assert info.value.fields == [
        "counts.train.n_images",
        "counts.val.by_origin.external",
        "counts.test.by_origin.external",
        "counts.train.by_source.b-src",  # sorted by the original source_id
        "counts.train.by_source.<invalid source_id>",
    ]
    # Without the data section only the sources are checked.
    with pytest.raises(report_mod.InvalidCountsError) as info:
        report_mod.check_counts(metrics, data_section=False)
    assert info.value.fields == [
        "counts.train.by_source.b-src",
        "counts.train.by_source.<invalid source_id>",
    ]


def test_check_counts_accepts_the_base_and_no_sources() -> None:
    report_mod.check_counts(_base(), data_section=True)
    metrics = _base()
    del metrics["counts"]["train"]["by_source"]
    report_mod.check_counts(metrics, data_section=True)
    report_mod.check_counts({}, data_section=False)


def test_check_counts_by_origin_not_an_object() -> None:
    metrics = _base()
    metrics["counts"]["train"]["by_origin"] = [11]
    metrics["counts"]["val"] = "x"
    with pytest.raises(report_mod.InvalidCountsError) as info:
        report_mod.check_counts(metrics, data_section=True)
    assert info.value.fields == [
        "counts.train.by_origin.external",
        "counts.val.by_origin.external",
    ]


def test_message_never_has_the_value() -> None:
    metrics = _base()
    marker = uuid4().hex
    metrics["counts"]["train"]["by_source"] = {"synthetic": f"x\n{marker}"}
    with pytest.raises(report_mod.InvalidCountsError) as info:
        report_mod.release_notes(SHA, metrics, load_external_sources(Path("/nonexistent.csv")))
    assert marker not in str(info.value)
    assert str(info.value) == "invalid count in metrics.json: counts.train.by_source.synthetic"


# ---------- 4.1: release-notes ----------


def _notes(tmp_path: Path, metrics: dict, capsys: pytest.CaptureFixture) -> tuple[int, str, str]:
    model_dir = _model_dir(tmp_path, metrics)
    out = tmp_path / "notes.md"
    argv = ["release-notes", "--model-dir", str(model_dir), "--external-sources"]
    code = report_mod.main([*argv, str(_registry(tmp_path)), "--output", str(out)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_release_notes_valid_counts_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    code, out, _ = _notes(tmp_path, _base(), capsys)
    assert code == 0 and out == ""
    text = (tmp_path / "notes.md").read_text(encoding="utf-8")
    assert NOTES_LINE in text.splitlines()


@pytest.mark.parametrize("value", [FORGED, True, -3, 1.5, 11.0, None, "11"])
def test_release_notes_invalid_count(
    tmp_path: Path, capsys: pytest.CaptureFixture, value: object
) -> None:
    metrics = _base()
    metrics["counts"]["train"]["by_source"]["synthetic"] = value
    code, out, err = _notes(tmp_path, metrics, capsys)
    assert code == 2 and out == ""
    assert not (tmp_path / "notes.md").exists()
    assert err.splitlines() == [
        "release-notes failed: invalid count in metrics.json: counts.train.by_source.synthetic"
    ]
    assert "forged" not in err


def test_release_notes_invalid_count_keeps_output(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    (tmp_path / "notes.md").write_text("antigo\n", encoding="utf-8")
    metrics = _base()
    metrics["counts"]["train"]["by_source"]["synthetic"] = FORGED
    code, _, _ = _notes(tmp_path, metrics, capsys)
    assert code == 2
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "antigo\n"


def test_release_notes_zero_count(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    metrics = _base()
    metrics["counts"]["train"]["by_source"]["synthetic"] = 0
    code, _, _ = _notes(tmp_path, metrics, capsys)
    assert code == 0
    text = (tmp_path / "notes.md").read_text(encoding="utf-8")
    assert any(line.startswith("- `synthetic`: 0 imagens, CC0-1.0. ") for line in text.splitlines())


def test_release_notes_counts_before_missing_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    marker = uuid4().hex
    metrics = _base()
    metrics["counts"]["train"]["by_source"] = {f"bad{marker}‮": "x\ny", "synthetic": 11}
    code, out, err = _notes(tmp_path, metrics, capsys)
    assert code == 2 and out == ""
    assert not (tmp_path / "notes.md").exists()
    assert "invalid count in metrics.json: counts.train.by_source.<invalid source_id>" in err
    assert marker not in err and "‮" not in err
    assert "source not in registry" not in err


def test_release_notes_other_fields_not_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Only the counts of the notes are checked by release-notes."""
    metrics = _base()
    metrics["counts"]["train"]["n_images"] = "x"
    del metrics["counts"]["val"]
    code, _, _ = _notes(tmp_path, metrics, capsys)
    assert code == 0


def test_release_notes_registry_problem_before_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    metrics = _base()
    metrics["counts"]["train"]["by_source"]["synthetic"] = True
    model_dir = _model_dir(tmp_path, metrics)
    registry = _write_csv(
        tmp_path / "bad.csv", [*EXTERNAL_SOURCE_COLUMNS, "notes"], [[*SYNTHETIC_SOURCE, ""]]
    )
    argv = ["release-notes", "--model-dir", str(model_dir), "--external-sources", str(registry)]
    assert report_mod.main(argv) == 2
    err = capsys.readouterr().err
    assert "unexpected_header" in err
    assert "invalid count" not in err


# ---------- 4.1: changelog ----------


def _changelog(
    tmp_path: Path, metrics: dict, capsys: pytest.CaptureFixture, append: bool = True
) -> tuple[int, str, str]:
    model_dir = _model_dir(tmp_path, metrics)
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# CHANGELOG\n", encoding="utf-8")
    argv = ["changelog", "--model-dir", str(model_dir), "--external-sources"]
    argv.append(str(_registry(tmp_path)))
    if append:
        argv += ["--append", str(changelog)]
    code = report_mod.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_changelog_valid_counts(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    code, out, _ = _changelog(tmp_path, _base(), capsys)
    assert code == 0
    assert "- Treino: 11 imagens externas de 55 (0,2000)." in out.splitlines()
    assert len((tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")) > len("# CHANGELOG\n")


def _edit(path: str, value: object, delete: bool = False):
    def apply(metrics: dict) -> None:
        *parents, last = path.split(".")
        node = metrics
        for key in parents:
            node = node[key]
        if delete:
            del node[last]
        else:
            node[last] = value

    return apply


MARKER = uuid4().hex
CHANGELOG_CASES = [
    (_edit("counts.train.by_source.synthetic", FORGED), "counts.train.by_source.synthetic"),
    (_edit("counts.train.n_images", f"x\nINJ{MARKER}"), "counts.train.n_images"),
    (_edit("counts.val.by_origin.external", True), "counts.val.by_origin.external"),
    (_edit("counts.test.by_origin.external", -1), "counts.test.by_origin.external"),
    (_edit("counts.train.by_origin.external", 1.5), "counts.train.by_origin.external"),
    (_edit("counts.val.by_origin.external", None, True), "counts.val.by_origin.external"),
    (_edit("counts.test.by_origin", None, True), "counts.test.by_origin.external"),
    (_edit("counts.train.n_images", None, True), "counts.train.n_images"),
    (_edit("counts.train.n_images", 55.0), "counts.train.n_images"),
    (_edit("counts.val", None, True), "counts.val.by_origin.external"),
]


@pytest.mark.parametrize(("edit", "field"), CHANGELOG_CASES)
def test_changelog_invalid_count(
    tmp_path: Path, capsys: pytest.CaptureFixture, edit, field: str
) -> None:
    metrics = _base()
    edit(metrics)
    code, out, err = _changelog(tmp_path, metrics, capsys)
    assert code == 2 and out == ""
    assert (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8") == "# CHANGELOG\n"
    assert err.splitlines() == [f"report failed: invalid count in metrics.json: {field}"]
    assert "forged" not in err and MARKER not in err


def test_changelog_without_by_origin_is_not_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    metrics = _base()
    for split_name in ("train", "val", "test"):
        del metrics["counts"][split_name]["by_origin"]
    metrics["counts"]["train"]["n_images"] = "x"
    metrics["counts"]["train"]["by_source"]["synthetic"] = "x\ny"
    code, out, _ = _changelog(tmp_path, metrics, capsys)
    assert code == 0
    assert "### Dados" not in out


def test_changelog_invalid_source_id_line(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    marker = uuid4().hex
    metrics = _base()
    metrics["counts"]["train"]["by_source"] = {f"bad{marker}‮": 1, "synthetic": 11}
    code, out, _ = _changelog(tmp_path, metrics, capsys, append=False)
    assert code == 0
    section = out.split("### Dados", 1)[1].split("### O que mudou", 1)[0]
    assert [line for line in section.splitlines() if line.startswith("- `")] == [
        "- `<invalid source_id>`: 1 imagens, licença não encontrada no registro",
        "- `synthetic`: 11 imagens, CC0-1.0. Crédito: Synthetic test images",
    ]
    assert marker not in out and "‮" not in out


def test_data_section_checks_counts() -> None:
    metrics = _base()
    metrics["counts"]["train"]["n_images"] = True
    with pytest.raises(report_mod.InvalidCountsError):
        report_mod.data_section(metrics, {})


# ---------- 4.2: --max-external-fraction ----------


@pytest.mark.parametrize("text", ["1e-400", "2e-324", "0", "-0.1", "1.0000001", "nan", "x"])
def test_fraction_argument_refused(text: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        split._fraction_argument(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1e-300", 1e-300), ("5e-324", 5e-324), ("0.30000000000000000001", 0.3), ("1", 1.0)],
)
def test_fraction_argument_accepted(text: str, expected: float) -> None:
    assert split._fraction_argument(text) == expected


def test_split_cli_underflow(dataset: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    splits = tmp_path / "splits"
    splits.mkdir()
    base = ["--dataset-dir", str(dataset), "--splits-dir", str(splits)]
    base += ["--external-sources", str(tmp_path / "absent.csv")]
    assert split.main([*base, "--max-external-fraction", "1e-400"]) == 2
    assert "Traceback" not in capsys.readouterr().err
    assert list(splits.iterdir()) == []
    assert split.main([*base, "--max-external-fraction", "1e-300"]) == 0
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["max_external_fraction"] == 1e-300


# ---------- 4.4: exact header ----------


def test_parse_csv_exact_header_only_when_asked() -> None:
    data_bytes = b"b,a,extra\n1,2,3\n"
    loose = parse_csv(data_bytes, "x.csv", ("a", "b"))
    assert loose.problems == [] and len(loose.rows) == 1
    exact = parse_csv(data_bytes, "x.csv", ("a", "b"), exact_header=True)
    assert [p.code for p in exact.problems] == ["unexpected_header"]
    assert exact.rows == []
    assert (exact.problems[0].line, exact.problems[0].image_path) == (1, None)
    assert "a,b" in exact.problems[0].message and "extra" not in exact.problems[0].message
    ok = parse_csv(b"a,b\n1,2\n", "x.csv", ("a", "b"), exact_header=True)
    assert ok.problems == [] and len(ok.rows) == 1


def test_parse_csv_missing_column_wins() -> None:
    table = parse_csv(b"a,extra\n1,2\n", "x.csv", ("a", "b"), exact_header=True)
    assert [p.code for p in table.problems] == ["missing_column"]


@pytest.fixture(scope="module")
def _origin_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_synthetic_dataset(
        tmp_path_factory.mktemp("origin037") / "ds",
        contributor_items_per_stratum=1,
        external_items_per_stratum=1,
    )


@pytest.fixture
def origin_dataset(_origin_template: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(_origin_template, tmp_path / "ds"))


def _read_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8", newline="") as fh:
        records = list(csv.reader(fh))
    return records[0], records[1:]


def _rewrite(path: Path, transform) -> None:
    header, rows = _read_rows(path)
    new_header, new_rows = transform(header, rows)
    _write_csv(path, new_header, new_rows)


def _extra(header, rows):
    return [*header, "notes"], [[*row, ""] for row in rows]


def _swap(a: int, b: int):
    def apply(header, rows):
        def swap(values):
            values = list(values)
            values[a], values[b] = values[b], values[a]
            return values

        return swap(header), [swap(row) for row in rows]

    return apply


def _repeat(index: int):
    return lambda header, rows: ([*header, header[index]], [[*row, row[index]] for row in rows])


def _trailing_comma(header, rows):
    return [*header, ""], [[*row, ""] for row in rows]


def _problems(root: Path) -> list:
    with pytest.raises(ManifestError) as info:
        load_manifest(root, external_sources=root / "external_sources.csv")
    return info.value.problems


@pytest.mark.parametrize("transform", [_extra, _swap(1, 2), _repeat(1), _trailing_comma])
def test_sources_unexpected_header(origin_dataset: Path, transform) -> None:
    _rewrite(origin_dataset / "sources.csv", transform)
    problems = _problems(origin_dataset)
    of_file = [p for p in problems if p.file == "sources.csv"]
    assert [(p.code, p.line, p.image_path) for p in of_file] == [("unexpected_header", 1, None)]
    assert not any(p.code in ("missing_source", "missing_column") for p in problems)
    assert ",".join(SOURCE_COLUMNS) in of_file[0].message


def test_sources_unexpected_header_in_load_sources(origin_dataset: Path) -> None:
    _rewrite(origin_dataset / "sources.csv", _extra)
    registry = load_external_sources(origin_dataset / "external_sources.csv")
    with pytest.raises(ManifestError) as info:
        data.load_sources(origin_dataset, registry)
    assert [p.code for p in info.value.problems] == ["unexpected_header"]


def test_sources_validate_cli(origin_dataset: Path, capsys: pytest.CaptureFixture) -> None:
    _rewrite(origin_dataset / "sources.csv", _extra)
    argv = ["validate", "--dataset-dir", str(origin_dataset), "--external-sources"]
    assert data.main([*argv, str(origin_dataset / "external_sources.csv")]) == 2
    assert "count unexpected_header: 1" in capsys.readouterr().out.splitlines()


def test_sources_missing_column_without_unexpected_header(origin_dataset: Path) -> None:
    _rewrite(origin_dataset / "sources.csv", lambda h, r: (h[:-1], [row[:-1] for row in r]))
    problems = _problems(origin_dataset)
    codes = [p.code for p in problems if p.file == "sources.csv"]
    assert codes == ["missing_column"]


def test_sources_bom_is_missing_column(origin_dataset: Path) -> None:
    path = origin_dataset / "sources.csv"
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    problems = [p for p in _problems(origin_dataset) if p.file == "sources.csv"]
    assert [p.code for p in problems] == ["missing_column"]
    assert "BOM" in problems[0].message


@pytest.mark.parametrize("transform", [_extra, _swap(1, 2), _repeat(3), _trailing_comma])
def test_registry_unexpected_header(
    origin_dataset: Path, tmp_path: Path, capsys: pytest.CaptureFixture, transform
) -> None:
    registry = origin_dataset / "external_sources.csv"
    _rewrite(registry, transform)
    problems = _problems(origin_dataset)
    of_registry = [p for p in problems if p.file == "external_sources.csv"]
    assert [(p.code, p.line, p.image_path) for p in of_registry] == [("unexpected_header", 1, None)]
    # No source is loaded: the external lines of sources.csv cannot find theirs.
    assert any(p.code == "unknown_source_id" for p in problems)
    with pytest.raises(ManifestError) as info:
        load_external_sources(registry)
    assert [p.code for p in info.value.problems] == ["unexpected_header"]
    model_dir = _model_dir(tmp_path, _base())
    argv = ["release-notes", "--model-dir", str(model_dir), "--external-sources", str(registry)]
    assert report_mod.main(argv) == 2
    assert capsys.readouterr().out == ""


def test_registry_repeated_license_is_refused(origin_dataset: Path) -> None:
    """CA-08 (c): a second ``license`` column cannot override the first one."""
    registry = origin_dataset / "external_sources.csv"
    header, rows = _read_rows(registry)
    index = header.index("license")
    rows = [[*row[:index], "CC-BY-NC-4.0", *row[index + 1 :], "CC0-1.0"] for row in rows]
    _write_csv(registry, [*header, "license"], rows)
    with pytest.raises(ManifestError) as info:
        load_external_sources(registry)
    assert [p.code for p in info.value.problems] == ["unexpected_header"]


def test_registry_exact_header_loads(origin_dataset: Path) -> None:
    sources = load_external_sources(origin_dataset / "external_sources.csv")
    assert list(sources) == ["synthetic"]


def test_repository_registry_has_the_exact_header() -> None:
    assert load_external_sources(ML / "external_sources.csv") is not None


def test_manifest_keeps_the_loose_header(dataset: Path) -> None:
    """The manifest still accepts an extra column (SPEC-011 section 4.1)."""
    _rewrite(dataset / "manifest.csv", _extra)
    assert len(load_manifest(dataset, external_sources=dataset / "absent.csv")) == 88


# ---------- 4.5: synthetic generator ----------


def test_generator_refuses_collision(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    with pytest.raises(ValueError, match="items_per_stratum") as info:
        make_synthetic_dataset(
            root, items_per_stratum=101, images_per_item=1, contributor_items_per_stratum=1
        )
    assert "contributor_items_per_stratum" in str(info.value)
    assert not root.exists()


def test_generator_limit_and_no_contributor(tmp_path: Path) -> None:
    root = make_synthetic_dataset(
        tmp_path / "limit",
        items_per_stratum=100,
        images_per_item=1,
        contributor_items_per_stratum=1,
    )
    with (root / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    labels: dict[str, set[tuple[str, str]]] = {}
    for row in rows:
        labels.setdefault(row["item_id"], set()).add((row["object_type"], row["grade"]))
    assert len(labels) == 1111
    assert all(len(pairs) == 1 for pairs in labels.values())
    load_manifest(root, external_sources=tmp_path / "absent.csv")
    plain = make_synthetic_dataset(
        tmp_path / "plain",
        items_per_stratum=101,
        images_per_item=1,
        contributor_items_per_stratum=0,
    )
    with (plain / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        assert len(list(csv.DictReader(fh))) == 1111


# ---------- 4.6: export_onnx finally (static) ----------


def _is_call_to(node: ast.AST, dotted: str) -> bool:
    return isinstance(node, ast.Call) and ast.unparse(node.func) == dotted


def test_export_logs_warnings_in_finally() -> None:
    tree = ast.parse((ML / "src" / "qc_ml" / "export.py").read_text(encoding="utf-8"))
    func = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "export_onnx"
    )
    tries = [
        n
        for n in ast.walk(func)
        if isinstance(n, ast.Try)
        and any(_is_call_to(c, "_log_export_warnings") for f in n.finalbody for c in ast.walk(f))
        and any(_is_call_to(c, "torch.onnx.export") for b in n.body for c in ast.walk(b))
    ]
    assert len(tries) == 1
    in_finally = {
        id(c)
        for n in ast.walk(func)
        if isinstance(n, ast.Try)
        for f in n.finalbody
        for c in ast.walk(f)
    }
    calls = [c for c in ast.walk(func) if _is_call_to(c, "_log_export_warnings")]
    assert calls and all(id(c) in in_finally for c in calls)
