"""Acceptance tests for SPEC-037 (ML maintenance: metrics.json counts in the Release notes and in
the CHANGELOG, fraction underflow, exact source headers, synthetic generator and export warnings).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test per CA (``test_caNN_*``); tests named ``test_extra_*`` are exploratory
edge cases around the SPEC that no CA spells out.

Rules followed (``docs/architecture.md`` §10, R-11 and R-14): every dataset is synthetic
(``make_synthetic_dataset``) and lives under ``tmp_path``; nothing under ``ml/data/`` is read; the
``metrics.json`` of CA-01 to CA-05 is written by the test (no torch, no pipeline); the CLIs run
through ``python -m`` in a subprocess; nothing is mocked besides the temporary file system and, in
CA-11 (marked ``slow``, skipped without torch), ``torch.onnx.export``.
"""

from __future__ import annotations

import ast
import copy
import csv
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import uuid
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from qc_ml.data import load_external_sources, load_manifest
from qc_ml.errors import ManifestError, ManifestProblem
from qc_ml.synthetic import make_synthetic_dataset

pytestmark = pytest.mark.acceptance

REPO_ROOT = Path(__file__).resolve().parents[3]
ML_ROOT = REPO_ROOT / "ml"
EXPORT_PY = ML_ROOT / "src" / "qc_ml" / "export.py"
TINY_SCRIPT = ML_ROOT / "scripts" / "make_tiny_fixture.py"
README = ML_ROOT / "README.md"
MODEL_SHA = "0123456789abcdef" * 4 + "\n"
RLO = "‮"
SOURCES_HEADER = ["image_path", "origin", "contributor", "source_id", "source_ref", "input_sha256"]
REGISTRY_HEADER = [
    "source_id",
    "title",
    "url",
    "license",
    "license_url",
    "attribution",
    "retrieved_at",
]
METRICS_BASE: dict[str, Any] = {
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
SYNTHETIC_NOTES_LINE = (
    "- `synthetic`: 11 imagens, CC0-1.0. Crédito: Synthetic test images | Licença: "
    "https://creativecommons.org/publicdomain/zero/1.0/ | Fonte: https://example.org/synthetic"
)
SYNTHETIC_CHANGELOG_LINE = "- `synthetic`: 11 imagens, CC0-1.0. Crédito: Synthetic test images"
FORGED = "11 imagens\n- `forged`: 9"
INVALID_PREFIX = "invalid count in metrics.json: "


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _inside(path: Path, root: Path) -> Path:
    """Fail unless ``path`` is inside ``root`` (guard before any write or delete)."""
    resolved = Path(path).resolve()
    assert resolved.is_relative_to(Path(root).resolve()), f"{resolved} is outside {root}"
    return resolved


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["HF_HUB_OFFLINE"] = "1"
    return env


def run_module(module: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """``python -m <module> <args>`` in a subprocess (never pytest), text mode in UTF-8."""
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        env=_env(),
        check=False,
    )


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def read_dicts(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def problems_of(excinfo: pytest.ExceptionInfo[ManifestError]) -> list[ManifestProblem]:
    problems = list(excinfo.value.problems)
    assert problems, "ManifestError without problems"
    return problems


def model_dir(tmp_path: Path, metrics: dict[str, Any] | str) -> Path:
    """``<dir>`` of the common context: ``model.sha256`` + the given ``metrics.json``."""
    target = _inside(tmp_path / "model", tmp_path)
    target.mkdir(exist_ok=True)
    (target / "model.sha256").write_text(MODEL_SHA, encoding="utf-8")
    body = metrics if isinstance(metrics, str) else json.dumps(metrics, ensure_ascii=False)
    (target / "metrics.json").write_text(body, encoding="utf-8")
    return target


def edited(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    """The metrics base with one field changed (``value is _DELETE`` removes the key)."""
    metrics = copy.deepcopy(METRICS_BASE)
    node = metrics
    for key in path[:-1]:
        node = node[key]
    if value is _DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return metrics


_DELETE = object()


def release_notes(
    tmp_path: Path, model: Path, registry: Path, output: Path | None
) -> subprocess.CompletedProcess[str]:
    args = ["release-notes", "--model-dir", str(model), "--external-sources", str(registry)]
    if output is not None:
        args += ["--output", str(output)]
    return run_module("qc_ml.report", args, tmp_path)


def changelog(
    tmp_path: Path, model: Path, registry: Path, append: Path | None
) -> subprocess.CompletedProcess[str]:
    args = ["changelog", "--model-dir", str(model), "--external-sources", str(registry)]
    if append is not None:
        args += ["--append", str(append)]
    return run_module("qc_ml.report", args, tmp_path)


def data_section(entry: str) -> list[str]:
    """Lines of the ``### Dados`` section of a CHANGELOG entry (until the next heading)."""
    lines = entry.splitlines()
    assert "### Dados" in lines, entry
    start = lines.index("### Dados") + 1
    section: list[str] = []
    for line in lines[start:]:
        if line.startswith("#"):
            break
        section.append(line)
    return section


def source_lines(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.startswith("- `")]


def invalid_lines(stderr: str) -> list[str]:
    """The ``<campo>`` of every ``invalid count in metrics.json: <campo>`` line of stderr."""
    out = []
    for line in stderr.splitlines():
        if INVALID_PREFIX in line:
            out.append(line.split(INVALID_PREFIX, 1)[1])
    return out


def _gen(factory: pytest.TempPathFactory, name: str, **kwargs: Any) -> Path:
    return make_synthetic_dataset(factory.mktemp(name) / "ds", **kwargs)


@pytest.fixture(scope="module")
def _registry_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """``<reg>``: the ``external_sources.csv`` written by the generator (SPEC-035 §4.7)."""
    root = _gen(tmp_path_factory, "s037_reg", external_items_per_stratum=1)
    return root / "external_sources.csv"


@pytest.fixture
def registry(_registry_template: Path, tmp_path: Path) -> Path:
    target = _inside(tmp_path / "external_sources.csv", tmp_path)
    shutil.copyfile(_registry_template, target)
    return target


@pytest.fixture(scope="module")
def _mixed_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The CA-02 dataset of SPEC-035 (1 contributor and 1 external item per stratum)."""
    return _gen(
        tmp_path_factory,
        "s037_mixed",
        contributor_items_per_stratum=1,
        external_items_per_stratum=1,
    )


@pytest.fixture
def ds_mixed(_mixed_template: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(_mixed_template, _inside(tmp_path / "ds", tmp_path)))


@pytest.fixture(scope="module")
def _plain_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _gen(tmp_path_factory, "s037_plain")


@pytest.fixture
def ds_plain(_plain_template: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(_plain_template, _inside(tmp_path / "ds", tmp_path)))


# ---------------------------------------------------------------------------------------------
# CA-01: counts in the release-notes (section 4.1)
# ---------------------------------------------------------------------------------------------


def test_ca01_release_notes_valid_base(tmp_path: Path, registry: Path) -> None:
    model = model_dir(tmp_path, METRICS_BASE)
    notes = tmp_path / "notes.md"
    proc = release_notes(tmp_path, model, registry, notes)
    assert proc.returncode == 0, proc.stderr
    assert SYNTHETIC_NOTES_LINE in notes.read_text(encoding="utf-8").splitlines()


INVALID_VALUES = [FORGED, True, -3, 1.5, "11.0-raw", None, "11"]
INVALID_IDS = ["forged-text", "true", "minus-3", "1.5", "11.0", "null", "string-11"]


@pytest.mark.parametrize("value", INVALID_VALUES, ids=INVALID_IDS)
def test_ca01_release_notes_invalid_count(tmp_path: Path, registry: Path, value: Any) -> None:
    metrics: dict[str, Any] | str
    if value == "11.0-raw":
        # 11.0 must reach json.loads written as a decimal: patch the serialised text.
        text = json.dumps(METRICS_BASE)
        assert text.count('"synthetic": 11}') == 1
        metrics = text.replace('"synthetic": 11}', '"synthetic": 11.0}')
    else:
        metrics = edited(("counts", "train", "by_source", "synthetic"), value)
    model = model_dir(tmp_path, metrics)
    notes = tmp_path / "notes.md"
    proc = release_notes(tmp_path, model, registry, notes)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert proc.stdout == ""
    assert not notes.exists()
    assert f"{INVALID_PREFIX}counts.train.by_source.synthetic" in proc.stderr
    assert "forged" not in proc.stderr
    assert "Traceback" not in proc.stderr


def test_ca01_release_notes_invalid_count_keeps_output(tmp_path: Path, registry: Path) -> None:
    model = model_dir(tmp_path, edited(("counts", "train", "by_source", "synthetic"), FORGED))
    notes = tmp_path / "notes.md"
    notes.write_bytes(b"antigo\n")
    proc = release_notes(tmp_path, model, registry, notes)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert proc.stdout == ""
    assert notes.read_bytes() == b"antigo\n"
    assert f"{INVALID_PREFIX}counts.train.by_source.synthetic" in proc.stderr
    assert "forged" not in proc.stderr


def test_ca01_release_notes_zero_count(tmp_path: Path, registry: Path) -> None:
    model = model_dir(tmp_path, edited(("counts", "train", "by_source", "synthetic"), 0))
    notes = tmp_path / "notes.md"
    proc = release_notes(tmp_path, model, registry, notes)
    assert proc.returncode == 0, proc.stderr
    lines = source_lines(notes.read_text(encoding="utf-8").splitlines())
    assert len(lines) == 1, lines
    assert lines[0].startswith("- `synthetic`: 0 imagens, CC0-1.0. "), lines


# ---------------------------------------------------------------------------------------------
# CA-02: release-notes, counts checked before the missing sources (section 4.1)
# ---------------------------------------------------------------------------------------------


def test_ca02_release_notes_counts_before_missing_sources(tmp_path: Path, registry: Path) -> None:
    marker = uuid.uuid4().hex
    by_source = {f"bad{marker}{RLO}": "x\ny", "synthetic": 11}
    model = model_dir(tmp_path, edited(("counts", "train", "by_source"), by_source))
    notes = tmp_path / "notes.md"
    proc = release_notes(tmp_path, model, registry, notes)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert proc.stdout == ""
    assert not notes.exists()
    assert f"{INVALID_PREFIX}counts.train.by_source.<invalid source_id>" in proc.stderr
    assert marker not in proc.stderr
    assert RLO not in proc.stderr
    assert "source not in registry" not in proc.stderr


# ---------------------------------------------------------------------------------------------
# CA-03: counts in the changelog (section 4.1)
# ---------------------------------------------------------------------------------------------


def test_ca03_changelog_valid_base(tmp_path: Path, registry: Path) -> None:
    model = model_dir(tmp_path, METRICS_BASE)
    target = tmp_path / "CHANGELOG.md"
    target.write_bytes(b"# CHANGELOG\n")
    proc = changelog(tmp_path, model, registry, target)
    assert proc.returncode == 0, proc.stderr
    assert "- Treino: 11 imagens externas de 55 (0,2000)." in proc.stdout.splitlines()
    body = target.read_bytes()
    assert body.startswith(b"# CHANGELOG\n")
    assert len(body) > len(b"# CHANGELOG\n")


def _without(split: str, key: str) -> dict[str, Any]:
    return edited(("counts", split, key), _DELETE)


def _val_by_origin_without_external() -> dict[str, Any]:
    metrics = copy.deepcopy(METRICS_BASE)
    del metrics["counts"]["val"]["by_origin"]["external"]
    return metrics


CA03_CASES: list[tuple[str, Callable[[str], dict[str, Any]], str]] = [
    (
        "a",
        lambda m: edited(("counts", "train", "by_source", "synthetic"), FORGED),
        "counts.train.by_source.synthetic",
    ),
    ("b", lambda m: edited(("counts", "train", "n_images"), f"x\nINJ{m}"), "counts.train.n_images"),
    (
        "c",
        lambda m: edited(("counts", "val", "by_origin", "external"), True),
        "counts.val.by_origin.external",
    ),
    (
        "d",
        lambda m: edited(("counts", "test", "by_origin", "external"), -1),
        "counts.test.by_origin.external",
    ),
    (
        "e",
        lambda m: edited(("counts", "train", "by_origin", "external"), 1.5),
        "counts.train.by_origin.external",
    ),
    ("f", lambda m: _val_by_origin_without_external(), "counts.val.by_origin.external"),
    ("g", lambda m: _without("test", "by_origin"), "counts.test.by_origin.external"),
    ("h", lambda m: _without("train", "n_images"), "counts.train.n_images"),
]


@pytest.mark.parametrize(("case", "build", "field"), CA03_CASES, ids=[c[0] for c in CA03_CASES])
def test_ca03_changelog_invalid_count(
    tmp_path: Path, registry: Path, case: str, build: Callable[[str], dict[str, Any]], field: str
) -> None:
    marker = uuid.uuid4().hex
    model = model_dir(tmp_path, build(marker))
    target = tmp_path / "CHANGELOG.md"
    target.write_bytes(b"# CHANGELOG\n")
    proc = changelog(tmp_path, model, registry, target)
    assert proc.returncode == 2, (case, proc.stdout, proc.stderr)
    assert proc.stdout == ""
    assert target.read_bytes() == b"# CHANGELOG\n"
    assert f"{INVALID_PREFIX}{field}" in proc.stderr, proc.stderr
    assert "forged" not in proc.stderr
    assert marker not in proc.stderr
    assert "Traceback" not in proc.stderr


# ---------------------------------------------------------------------------------------------
# CA-04: metrics.json older than SPEC-035 (no by_origin) is not checked
# ---------------------------------------------------------------------------------------------


def test_ca04_changelog_without_by_origin_not_checked(tmp_path: Path, registry: Path) -> None:
    metrics = copy.deepcopy(METRICS_BASE)
    for split in ("train", "val", "test"):
        del metrics["counts"][split]["by_origin"]
    metrics["counts"]["train"]["n_images"] = "x"
    model = model_dir(tmp_path, metrics)
    target = tmp_path / "CHANGELOG.md"
    target.write_bytes(b"# CHANGELOG\n")
    proc = changelog(tmp_path, model, registry, target)
    assert proc.returncode == 0, proc.stderr
    assert "### Dados" not in proc.stdout.splitlines()
    appended = target.read_text(encoding="utf-8")
    assert appended.startswith("# CHANGELOG\n") and len(appended) > len("# CHANGELOG\n")
    assert "### Dados" not in appended.splitlines()


# ---------------------------------------------------------------------------------------------
# CA-05: <invalid source_id> in the CHANGELOG (section 4.3)
# ---------------------------------------------------------------------------------------------


def test_ca05_changelog_invalid_source_id_line(tmp_path: Path, registry: Path) -> None:
    marker = uuid.uuid4().hex
    by_source = {f"bad{marker}{RLO}": 1, "synthetic": 11}
    model = model_dir(tmp_path, edited(("counts", "train", "by_source"), by_source))
    proc = changelog(tmp_path, model, registry, None)
    assert proc.returncode == 0, proc.stderr
    lines = source_lines(data_section(proc.stdout))
    assert lines == [
        "- `<invalid source_id>`: 1 imagens, licença não encontrada no registro",
        SYNTHETIC_CHANGELOG_LINE,
    ], lines
    assert marker not in proc.stdout
    assert RLO not in proc.stdout


# ---------------------------------------------------------------------------------------------
# CA-06: --max-external-fraction underflow (section 4.2)
# ---------------------------------------------------------------------------------------------


def split_cli(root: Path, splits: Path, tmp_path: Path, x: str) -> subprocess.CompletedProcess[str]:
    args = ["--dataset-dir", str(root), "--splits-dir", str(splits)]
    args += ["--external-sources", str(tmp_path / "inexistente.csv")]
    args += ["--max-external-fraction", x]
    return run_module("qc_ml.split", args, tmp_path)


@pytest.mark.parametrize("x", ["1e-400", "2e-324"])
def test_ca06_underflow_refused(tmp_path: Path, ds_plain: Path, x: str) -> None:
    splits = _inside(tmp_path / "splits", tmp_path)
    splits.mkdir()
    proc = split_cli(ds_plain, splits, tmp_path, x)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "Traceback" not in proc.stderr
    assert list(splits.iterdir()) == []


@pytest.mark.parametrize(("x", "expected"), [("1e-300", 1e-300), ("0.30000000000000000001", 0.3)])
def test_ca06_representable_values_accepted(
    tmp_path: Path, ds_plain: Path, x: str, expected: float
) -> None:
    splits = _inside(tmp_path / "splits", tmp_path)
    splits.mkdir()
    proc = split_cli(ds_plain, splits, tmp_path, x)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["max_external_fraction"] == expected
    assert isinstance(meta["max_external_fraction"], float)


# ---------------------------------------------------------------------------------------------
# CA-07: exact header of sources.csv (section 4.4)
# ---------------------------------------------------------------------------------------------


def _sources_extra(rows: list[dict[str, str]]) -> tuple[list[str], list[list[str]]]:
    return [*SOURCES_HEADER, "notes"], [[r[c] for c in SOURCES_HEADER] + [""] for r in rows]


def _sources_swapped(rows: list[dict[str, str]]) -> tuple[list[str], list[list[str]]]:
    header = list(SOURCES_HEADER)
    header[1], header[2] = header[2], header[1]
    return header, [[r[c] for c in header] for r in rows]


def _sources_repeated(rows: list[dict[str, str]]) -> tuple[list[str], list[list[str]]]:
    return [*SOURCES_HEADER, "origin"], [
        [r[c] for c in SOURCES_HEADER] + [r["origin"]] for r in rows
    ]


CA07_CASES = [
    ("a-extra", _sources_extra),
    ("b-swapped", _sources_swapped),
    ("c-repeated", _sources_repeated),
]


@pytest.mark.parametrize(("case", "build"), CA07_CASES, ids=[c for c, _ in CA07_CASES])
def test_ca07_sources_unexpected_header(ds_mixed: Path, tmp_path: Path, case: str, build) -> None:
    rows = read_dicts(ds_mixed / "sources.csv")
    assert rows and list(rows[0]) == SOURCES_HEADER
    header, values = build(rows)
    write_csv(_inside(ds_mixed / "sources.csv", tmp_path), header, values)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_mixed, external_sources=ds_mixed / "external_sources.csv")
    problems = problems_of(excinfo)
    in_sources = [p for p in problems if p.file == "sources.csv"]
    assert len(in_sources) == 1, [str(p) for p in problems]
    assert in_sources[0].code == "unexpected_header"
    assert in_sources[0].line == 1
    assert in_sources[0].image_path is None
    assert not {p.code for p in problems} & {"missing_source", "missing_column"}, problems
    if case == "a-extra":
        proc = run_module(
            "qc_ml.data",
            [
                "validate",
                "--dataset-dir",
                str(ds_mixed),
                "--external-sources",
                str(ds_mixed / "external_sources.csv"),
            ],
            tmp_path,
        )
        assert proc.returncode == 2, (proc.stdout, proc.stderr)
        assert "count unexpected_header: 1" in proc.stdout + proc.stderr


def test_ca07_sources_missing_column_without_unexpected_header(
    ds_mixed: Path, tmp_path: Path
) -> None:
    rows = read_dicts(ds_mixed / "sources.csv")
    header = SOURCES_HEADER[:-1]
    write_csv(
        _inside(ds_mixed / "sources.csv", tmp_path), header, [[r[c] for c in header] for r in rows]
    )
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_mixed, external_sources=ds_mixed / "external_sources.csv")
    problems = problems_of(excinfo)
    assert any(p.code == "missing_column" and p.file == "sources.csv" for p in problems), problems
    assert not any(p.code == "unexpected_header" for p in problems), problems


# ---------------------------------------------------------------------------------------------
# CA-08: exact header of the registry (section 4.4)
# ---------------------------------------------------------------------------------------------


def _registry_extra(src: dict[str, str]) -> tuple[list[str], list[list[str]]]:
    return [*REGISTRY_HEADER, "notes"], [[src[c] for c in REGISTRY_HEADER] + [""]]


def _registry_swapped(src: dict[str, str]) -> tuple[list[str], list[list[str]]]:
    header = list(REGISTRY_HEADER)
    header[1], header[2] = header[2], header[1]
    return header, [[src[c] for c in header]]


def _registry_repeated_license(src: dict[str, str]) -> tuple[list[str], list[list[str]]]:
    first = dict(src, license="CC-BY-NC-4.0")
    return [*REGISTRY_HEADER, "license"], [[first[c] for c in REGISTRY_HEADER] + ["CC0-1.0"]]


CA08_CASES = [
    ("a-extra", _registry_extra),
    ("b-swapped", _registry_swapped),
    ("c-repeated-license", _registry_repeated_license),
]


def _the_header_problem(problems: list[ManifestProblem]) -> None:
    found = [
        p
        for p in problems
        if p.code == "unexpected_header" and p.file == "external_sources.csv" and p.line == 1
    ]
    assert len(found) == 1, [str(p) for p in problems]


@pytest.mark.parametrize(("case", "build"), CA08_CASES, ids=[c for c, _ in CA08_CASES])
def test_ca08_registry_unexpected_header(ds_mixed: Path, tmp_path: Path, case: str, build) -> None:
    reg_path = _inside(ds_mixed / "external_sources.csv", tmp_path)
    sources = read_dicts(reg_path)
    assert [s["source_id"] for s in sources] == ["synthetic"]
    assert sources[0]["license"] == "CC0-1.0"
    header, values = build(sources[0])
    write_csv(reg_path, header, values)

    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_mixed, external_sources=reg_path)
    _the_header_problem(problems_of(excinfo))

    with pytest.raises(ManifestError) as excinfo:
        load_external_sources(reg_path)
    _the_header_problem(problems_of(excinfo))

    model = model_dir(tmp_path, METRICS_BASE)
    proc = release_notes(tmp_path, model, reg_path, None)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert proc.stdout == ""


def test_ca08_registry_exact_header_loads(ds_mixed: Path) -> None:
    loaded = load_external_sources(ds_mixed / "external_sources.csv")
    assert set(loaded) == {"synthetic"}


# ---------------------------------------------------------------------------------------------
# CA-09: generator never makes contributor items collide with own items (section 4.5)
# ---------------------------------------------------------------------------------------------


def test_ca09_generator_refuses_collision(tmp_path: Path) -> None:
    root = _inside(tmp_path / "ds", tmp_path)
    with pytest.raises(ValueError):
        make_synthetic_dataset(
            root, items_per_stratum=101, images_per_item=1, contributor_items_per_stratum=1
        )
    assert not (root / "manifest.csv").exists()


def test_ca09_generator_limit_is_accepted(tmp_path: Path) -> None:
    root = _inside(tmp_path / "ds", tmp_path)
    make_synthetic_dataset(
        root, items_per_stratum=100, images_per_item=1, contributor_items_per_stratum=1
    )
    rows = read_dicts(root / "manifest.csv")
    items = {r["item_id"] for r in rows}
    assert len(items) == 1111

    numbered = [re.fullmatch(r"([SNO])-(\d+)", i) for i in items]
    assert all(numbered), sorted(i for i in items if not re.fullmatch(r"[SNO]-\d+", i))
    own = {p: 0 for p in "SNO"}
    known = {p: 0 for p in "SNO"}
    for match in numbered:
        assert match is not None
        letter, number = match.group(1), int(match.group(2))
        if number >= 501:
            known[letter] += 1
        else:
            own[letter] += 1
    assert own == {"S": 500, "N": 500, "O": 100}, own
    assert known == {"S": 5, "N": 5, "O": 1}, known
    contributor_items = {
        Path(r["image_path"]).name.split("__")[0]
        for r in read_dicts(root / "sources.csv")
        if r["origin"] == "contributor"
    }
    assert len(contributor_items) == 11
    assert all(int(i.split("-")[1]) >= 501 for i in contributor_items), contributor_items
    pairs: dict[str, set[tuple[str, str]]] = {}
    for r in rows:
        pairs.setdefault(r["item_id"], set()).add((r["object_type"], r["grade"]))
    assert all(len(v) == 1 for v in pairs.values())
    load_manifest(root, external_sources=tmp_path / "inexistente.csv")


def test_ca09_generator_without_contributor_unchanged(tmp_path: Path) -> None:
    root = _inside(tmp_path / "ds", tmp_path)
    make_synthetic_dataset(
        root, items_per_stratum=101, images_per_item=1, contributor_items_per_stratum=0
    )
    assert len(read_dicts(root / "manifest.csv")) == 1111


# ---------------------------------------------------------------------------------------------
# CA-10: _log_export_warnings in a finally around torch.onnx.export (static, section 4.6)
# ---------------------------------------------------------------------------------------------


def _call_name(node: ast.Call) -> str:
    parts: list[str] = []
    func: ast.AST = node.func
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return ".".join(reversed(parts))


def _calls(nodes: list[ast.stmt], name: str) -> list[ast.Call]:
    found = []
    for stmt in nodes:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Call) and _call_name(sub) == name:
                found.append(sub)
    return found


def _export_onnx_node() -> ast.FunctionDef:
    tree = ast.parse(EXPORT_PY.read_text(encoding="utf-8"))
    funcs = [
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "export_onnx"
    ]
    assert len(funcs) == 1
    return funcs[0]


def test_ca10_export_warnings_logged_in_finally() -> None:
    func = _export_onnx_node()
    tries = [n for n in ast.walk(func) if isinstance(n, ast.Try)]
    good = [
        t
        for t in tries
        if _calls(t.finalbody, "_log_export_warnings") and _calls(t.body, "torch.onnx.export")
    ]
    assert good, "no Try with torch.onnx.export in body and _log_export_warnings in finalbody"
    in_finally = {id(c) for t in tries for c in _calls(t.finalbody, "_log_export_warnings")}
    every = _calls(func.body, "_log_export_warnings")
    assert every, "export_onnx never calls _log_export_warnings"
    outside = [c.lineno for c in every if id(c) not in in_finally]
    assert outside == [], f"_log_export_warnings outside a finalbody at lines {outside}"


# ---------------------------------------------------------------------------------------------
# CA-11: warnings logged when torch.onnx.export raises (with torch, slow)
# ---------------------------------------------------------------------------------------------


def _tiny_net_class() -> type:
    spec = importlib.util.spec_from_file_location("partqc_tiny_fixture_037", TINY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TinyNet


@pytest.mark.slow
def test_ca11_export_logs_warnings_when_it_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    torch = pytest.importorskip("torch")
    from qc_ml.export import export_onnx

    marker1 = f"partqc-spec037-w-{uuid.uuid4().hex}"
    marker2 = f"partqc-spec037-e-{uuid.uuid4().hex}"

    def failing(*args: Any, **kwargs: Any) -> Any:
        warnings.warn(marker1, DeprecationWarning, stacklevel=1)
        raise RuntimeError(marker2)

    monkeypatch.setattr(torch.onnx, "export", failing)
    torch.manual_seed(0)
    model = _tiny_net_class()().eval()
    out = _inside(tmp_path / "export" / "model.onnx", tmp_path)
    caplog.set_level(logging.WARNING, logger="qc_ml.export")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(RuntimeError) as excinfo:
            export_onnx(model, out)
    assert marker2 in str(excinfo.value)
    records = [
        r for r in caplog.records if r.name == "qc_ml.export" and r.levelno == logging.WARNING
    ]
    assert len(records) == 1, [(r.name, r.levelname, r.getMessage()) for r in caplog.records]
    assert records[0].getMessage() == f"torch.onnx.export: {marker1}"


# ---------------------------------------------------------------------------------------------
# Exploratory (test_extra_*)
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["10000000000000000000000000000000", "-0"])
def test_extra_release_notes_big_int_and_negative_zero_are_valid(
    tmp_path: Path, registry: Path, raw: str
) -> None:
    text = json.dumps(METRICS_BASE).replace('"synthetic": 11}', f'"synthetic": {raw}}}')
    model = model_dir(tmp_path, text)
    proc = release_notes(tmp_path, model, registry, None)
    assert proc.returncode == 0, proc.stderr
    assert f"- `synthetic`: {int(raw)} imagens, CC0-1.0." in proc.stdout


@pytest.mark.parametrize("raw", ["1e2", "1E1", "false"])
def test_extra_release_notes_exponent_and_false_are_invalid(
    tmp_path: Path, registry: Path, raw: str
) -> None:
    text = json.dumps(METRICS_BASE).replace('"synthetic": 11}', f'"synthetic": {raw}}}')
    model = model_dir(tmp_path, text)
    proc = release_notes(tmp_path, model, registry, None)
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert f"{INVALID_PREFIX}counts.train.by_source.synthetic" in proc.stderr


def test_extra_release_notes_ignores_other_invalid_fields(tmp_path: Path, registry: Path) -> None:
    """§4.1: only by_source is checked by release-notes."""
    metrics = edited(("counts", "train", "n_images"), "x\nforged")
    metrics["counts"]["val"]["by_origin"]["external"] = True
    model = model_dir(tmp_path, metrics)
    proc = release_notes(tmp_path, model, registry, None)
    assert proc.returncode == 0, proc.stderr
    assert SYNTHETIC_NOTES_LINE in proc.stdout.splitlines()


def test_extra_changelog_one_line_per_invalid_field(tmp_path: Path, registry: Path) -> None:
    metrics = copy.deepcopy(METRICS_BASE)
    metrics["counts"]["train"]["n_images"] = None
    metrics["counts"]["val"]["by_origin"]["external"] = -2
    metrics["counts"]["test"]["by_origin"]["external"] = "0"
    metrics["counts"]["train"]["by_source"] = {"synthetic": 2.5, "zz-fora": False}
    model = model_dir(tmp_path, metrics)
    proc = changelog(tmp_path, model, registry, None)
    assert proc.returncode == 2
    assert proc.stdout == ""
    fields = invalid_lines(proc.stderr)
    assert sorted(fields) == sorted(
        [
            "counts.train.n_images",
            "counts.val.by_origin.external",
            "counts.test.by_origin.external",
            "counts.train.by_source.synthetic",
            "counts.train.by_source.zz-fora",
        ]
    ), proc.stderr
    assert len(fields) == len(set(fields)), proc.stderr


def test_extra_changelog_split_missing_is_invalid(tmp_path: Path, registry: Path) -> None:
    metrics = edited(("counts", "val"), _DELETE)
    model = model_dir(tmp_path, metrics)
    proc = changelog(tmp_path, model, registry, None)
    assert proc.returncode == 2, proc.stdout
    assert f"{INVALID_PREFIX}counts.val.by_origin.external" in proc.stderr


def test_extra_changelog_by_origin_not_object_is_invalid(tmp_path: Path, registry: Path) -> None:
    metrics = edited(("counts", "test", "by_origin"), [0, 0, 0])
    model = model_dir(tmp_path, metrics)
    proc = changelog(tmp_path, model, registry, None)
    assert proc.returncode == 2, proc.stdout
    assert f"{INVALID_PREFIX}counts.test.by_origin.external" in proc.stderr


def test_extra_changelog_valid_base_lines(tmp_path: Path, registry: Path) -> None:
    """The section text with valid counts (CA-13 of SPEC-035, unchanged)."""
    model = model_dir(tmp_path, METRICS_BASE)
    proc = changelog(tmp_path, model, registry, None)
    assert proc.returncode == 0, proc.stderr
    section = data_section(proc.stdout)
    assert "- Validação e teste: 0 e 0 imagens externas (ADR-020)." in section
    assert "- Treino: 11 imagens externas de 55 (0,2000)." in section
    assert source_lines(section) == [SYNTHETIC_CHANGELOG_LINE]


@pytest.mark.parametrize("x", ["0", "-0.1", "1.0000001", "nan", "inf", "-inf", "abc", "1e-400x"])
def test_extra_fraction_other_invalid_values(tmp_path: Path, ds_plain: Path, x: str) -> None:
    splits = _inside(tmp_path / "splits", tmp_path)
    splits.mkdir()
    proc = split_cli(ds_plain, splits, tmp_path, x)
    assert proc.returncode == 2, (x, proc.stdout, proc.stderr)
    assert "Traceback" not in proc.stderr
    assert list(splits.iterdir()) == []


def test_extra_fraction_one_is_accepted(tmp_path: Path, ds_plain: Path) -> None:
    splits = _inside(tmp_path / "splits", tmp_path)
    splits.mkdir()
    proc = split_cli(ds_plain, splits, tmp_path, "1")
    assert proc.returncode == 0, proc.stderr
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["max_external_fraction"] == 1.0


def test_extra_sources_trailing_comma_is_unexpected_header(ds_mixed: Path, tmp_path: Path) -> None:
    rows = read_dicts(ds_mixed / "sources.csv")
    write_csv(
        _inside(ds_mixed / "sources.csv", tmp_path),
        [*SOURCES_HEADER, ""],
        [[r[c] for c in SOURCES_HEADER] + [""] for r in rows],
    )
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_mixed, external_sources=ds_mixed / "external_sources.csv")
    problems = problems_of(excinfo)
    assert [p.code for p in problems if p.file == "sources.csv"] == ["unexpected_header"], problems


def test_extra_sources_bom_is_missing_column(ds_mixed: Path, tmp_path: Path) -> None:
    path = _inside(ds_mixed / "sources.csv", tmp_path)
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_mixed, external_sources=ds_mixed / "external_sources.csv")
    problems = problems_of(excinfo)
    missing = [p for p in problems if p.code == "missing_column" and p.file == "sources.csv"]
    assert missing, problems
    assert not any(p.code == "unexpected_header" for p in problems), problems


def test_extra_sources_crlf_still_accepted(ds_mixed: Path, tmp_path: Path) -> None:
    path = _inside(ds_mixed / "sources.csv", tmp_path)
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    reg_path = _inside(ds_mixed / "external_sources.csv", tmp_path)
    reg_path.write_bytes(reg_path.read_bytes().replace(b"\n", b"\r\n"))
    load_manifest(ds_mixed, external_sources=reg_path)
    assert set(load_external_sources(reg_path)) == {"synthetic"}


def test_extra_header_message_does_not_echo_read_header(ds_mixed: Path, tmp_path: Path) -> None:
    marker = f"col{uuid.uuid4().hex}"
    reg_path = _inside(ds_mixed / "external_sources.csv", tmp_path)
    src = read_dicts(reg_path)[0]
    write_csv(reg_path, [*REGISTRY_HEADER, marker], [[src[c] for c in REGISTRY_HEADER] + [""]])
    with pytest.raises(ManifestError) as excinfo:
        load_external_sources(reg_path)
    problem = [p for p in problems_of(excinfo) if p.code == "unexpected_header"][0]
    assert marker not in problem.message
    assert marker not in str(excinfo.value)
    assert all(col in problem.message for col in REGISTRY_HEADER), problem.message


def test_extra_manifest_extra_column_still_accepted(ds_plain: Path, tmp_path: Path) -> None:
    """§3.2: the manifest keeps the SPEC-011 rule (only a missing column is an error)."""
    path = _inside(ds_plain / "manifest.csv", tmp_path)
    rows = read_dicts(path)
    header = [*rows[0].keys(), "extra"]
    write_csv(path, header, [[*r.values(), "x"] for r in rows])
    load_manifest(ds_plain, external_sources=tmp_path / "inexistente.csv")


def test_extra_changelog_registry_unexpected_header_exits_2(ds_mixed: Path, tmp_path: Path) -> None:
    reg_path = _inside(ds_mixed / "external_sources.csv", tmp_path)
    header, values = _registry_extra(read_dicts(reg_path)[0])
    write_csv(reg_path, header, values)
    model = model_dir(tmp_path, METRICS_BASE)
    proc = changelog(tmp_path, model, reg_path, None)
    assert proc.returncode == 2, proc.stdout
    assert proc.stdout == ""


def test_extra_generator_without_other_and_validation_before_mkdir(tmp_path: Path) -> None:
    root = _inside(tmp_path / "nested" / "ds", tmp_path)
    with pytest.raises(ValueError) as excinfo:
        make_synthetic_dataset(
            root,
            items_per_stratum=101,
            images_per_item=1,
            include_other=False,
            contributor_items_per_stratum=1,
        )
    message = str(excinfo.value)
    assert "items_per_stratum" in message and "contributor_items_per_stratum" in message
    assert not root.exists()


def test_extra_readme_mentions_exact_header() -> None:
    text = README.read_text(encoding="utf-8")
    assert "unexpected_header" in text
    assert "sources.csv" in text and "external_sources.csv" in text


@pytest.mark.slow
def test_extra_export_success_logs_each_warning_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    torch = pytest.importorskip("torch")
    from qc_ml.export import export_onnx

    marker = f"partqc-spec037-ok-{uuid.uuid4().hex}"
    original = torch.onnx.export

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        out = original(*args, **kwargs)
        warnings.warn(marker, DeprecationWarning, stacklevel=1)
        return out

    monkeypatch.setattr(torch.onnx, "export", wrapped)
    torch.manual_seed(0)
    model = _tiny_net_class()().eval()
    out = _inside(tmp_path / "export" / "model.onnx", tmp_path)
    caplog.set_level(logging.WARNING, logger="qc_ml.export")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        export_onnx(model, out)
    assert out.is_file() and out.stat().st_size > 0
    hits = [
        r
        for r in caplog.records
        if r.name == "qc_ml.export" and r.getMessage() == f"torch.onnx.export: {marker}"
    ]
    assert len(hits) == 1, [(r.name, r.getMessage()) for r in caplog.records]


def test_extra_release_notes_invalid_count_of_unregistered_source(
    tmp_path: Path, registry: Path
) -> None:
    """A valid-format id outside the registry with an invalid count: only the count is reported."""
    by_source = {"synthetic": 11, "zz-fora": "7\n- `forged`: 1"}
    model = model_dir(tmp_path, edited(("counts", "train", "by_source"), by_source))
    proc = release_notes(tmp_path, model, registry, None)
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert invalid_lines(proc.stderr) == ["counts.train.by_source.zz-fora"], proc.stderr
    assert "source not in registry" not in proc.stderr
    assert "forged" not in proc.stderr


@pytest.mark.parametrize("value", [None, [1, 2]])
def test_extra_changelog_by_origin_present_but_not_object_everywhere(
    tmp_path: Path, registry: Path, value: Any
) -> None:
    """``by_origin`` present (any type) generates the section, so the counts are required."""
    metrics = copy.deepcopy(METRICS_BASE)
    for split in ("train", "val", "test"):
        metrics["counts"][split]["by_origin"] = value
    model = model_dir(tmp_path, metrics)
    proc = changelog(tmp_path, model, registry, None)
    assert proc.returncode == 2, proc.stdout
    assert proc.stdout == ""
    assert sorted(invalid_lines(proc.stderr)) == sorted(
        f"counts.{s}.by_origin.external" for s in ("train", "val", "test")
    ), proc.stderr
