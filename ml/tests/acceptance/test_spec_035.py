"""Acceptance tests for SPEC-035 (qc-ml: image origins, external images only in train, credits).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test per CA (``test_caNN_*``); tests named ``test_extra_*`` are exploratory
edge cases around the SPEC that no CA spells out.

Rules followed (``docs/architecture.md`` §10, R-11 and R-14): every dataset is synthetic
(``make_synthetic_dataset`` plus images drawn here with Pillow) and lives under ``tmp_path``;
nothing under ``ml/data/`` is ever read; nothing is mocked besides the temporary file system; the
registry used is always ``<root>/external_sources.csv`` (the repository one only in CA-14); the
CLIs run through ``main(argv)`` or ``python -m`` in a subprocess; no test uses torch.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from PIL import Image

from qc_contracts import Grade
from qc_ml import data as data_mod
from qc_ml import evaluate as evaluate_mod
from qc_ml import split as split_mod
from qc_ml import thresholds as thresholds_mod
from qc_ml.data import (
    ITEM_ID_PATTERN,
    build_data_report,
    is_external_item,
    item_type_letter,
    load_external_sources,
    load_manifest,
)
from qc_ml.errors import ManifestError, ManifestProblem, SplitError, SplitIntegrityError
from qc_ml.split import item_history, load_split, make_split, rows_for
from qc_ml.synthetic import make_synthetic_dataset

pytestmark = pytest.mark.acceptance

REPO_ROOT = Path(__file__).resolve().parents[3]
ML_ROOT = REPO_ROOT / "ml"
TINY_MODEL = ML_ROOT / "tests" / "fixtures" / "tiny_model"
TINY_VERSION = "partqc-tiny035-v1"
GRADES = [g.value for g in Grade]
SPLITS = ("train", "val", "test")
ORIGINS = ("capture", "contributor", "external")

MANIFEST_HEADER = [
    "image_path",
    "item_id",
    "object_type",
    "grade",
    "labeler",
    "angle",
    "captured_at",
    "capture_device",
    "notes",
]
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
SYNTHETIC_SOURCE = {
    "source_id": "synthetic",
    "title": "Synthetic dataset",
    "url": "https://example.org/synthetic",
    "license": "CC0-1.0",
    "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
    "attribution": "Synthetic test images",
    "retrieved_at": "2026-10-20",
}
AA_SOURCE = {
    "source_id": "aa-fonte",
    "title": "Fonte AA",
    "url": "https://example.org/aa",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "attribution": "Fonte AA",
    "retrieved_at": "2026-10-20",
}
REPORT_KEYS_011 = {
    "generated_at",
    "manifest_sha256",
    "split_file",
    "split_sha256",
    "n_images",
    "n_items",
    "n_overridden",
    "n_excluded",
    "counts",
    "items_per_grade",
    "images_per_item",
    "below_target",
    "below_minimum",
}
REPORT_KEYS_035 = {"counts_by_origin", "n_contributors", "by_source", "external_fraction_train"}
METRIC_KEYS = {
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
}
SYNTH_DATA_LINE = "- `synthetic`: 11 imagens, CC0-1.0. Crédito: Synthetic test images"
SYNTH_NOTES_LINE = (
    "- `synthetic`: 11 imagens, CC0-1.0. Crédito: Synthetic test images | Licença: "
    "https://creativecommons.org/publicdomain/zero/1.0/ | Fonte: https://example.org/synthetic"
)
AA_NOTES_LINE = (
    "- `aa-fonte`: 2 imagens, CC-BY-4.0. Crédito: Fonte AA | Licença: "
    "https://creativecommons.org/licenses/by/4.0/ | Fonte: https://example.org/aa"
)
PATHS_LINE = (
    "Registro das fontes: `ml/external_sources.csv`. Histórico do modelo: `ml/models/CHANGELOG.md`."
)
NO_EXTERNAL_LINE = "Este modelo não usa imagens externas (ADR-020)."
NOTES_TITLE = "## Fontes externas e créditos"


# --------------------------------------------------------------------------------------------
# Helpers (synthetic data only, always under tmp_path)
# --------------------------------------------------------------------------------------------


def _inside(path: Path, root: Path) -> Path:
    """Fail unless ``path`` is inside ``root`` (guard before any write or delete)."""
    resolved = Path(path).resolve()
    assert resolved.is_relative_to(Path(root).resolve()), f"{resolved} is outside {root}"
    return resolved


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_sha(tag: str) -> str:
    return hashlib.sha256(f"spec035-{tag}".encode()).hexdigest()


def read_rows(root: Path) -> list[dict[str, str]]:
    with (root / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(root: Path, rows: list[dict[str, str]]) -> None:
    with (root / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def read_sources(root: Path) -> list[dict[str, str]]:
    with (root / "sources.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_sources(root: Path, rows: list[dict[str, str]], header: list[str] | None = None) -> None:
    header = header or SOURCES_HEADER
    write_csv(root / "sources.csv", header, [[r[c] for c in header] for r in rows])


def write_registry(path: Path, sources: list[dict[str, str]]) -> Path:
    write_csv(path, REGISTRY_HEADER, [[s[c] for c in REGISTRY_HEADER] for s in sources])
    return path


def write_jpeg(path: Path, color: tuple[int, int, int] = (230, 230, 225)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (64, 64), color)
    for x in range(24, 40):
        for y in range(10, 54):
            img.putpixel((x, y), (120, 120, 130))
    img.save(path, format="JPEG", quality=90)


def add_image(root: Path, item_id: str, object_type: str, grade: str | None, angle: int, ts: str):
    """Append one image (file + manifest row) in the SPEC-010 layout. ``ts`` = 20261101T100000Z."""
    rel = f"raw/{object_type}/{grade or '_'}/{item_id}__{angle}__{ts}.jpg"
    digest = hashlib.sha256(rel.encode()).digest()
    write_jpeg(root / rel, (200 + digest[0] % 50, 200 + digest[1] % 50, 200 + digest[2] % 50))
    captured = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[9:11]}:{ts[11:13]}:{ts[13:15]}Z"
    rows = read_rows(root)
    rows.append(
        {
            "image_path": rel,
            "item_id": item_id,
            "object_type": object_type,
            "grade": grade or "",
            "labeler": "a",
            "angle": str(angle),
            "captured_at": captured,
            "capture_device": "synthetic",
            "notes": "",
        }
    )
    write_rows(root, rows)
    return rel


def problems_of(excinfo: pytest.ExceptionInfo[ManifestError]) -> list[ManifestProblem]:
    problems = list(excinfo.value.problems)
    assert problems, "ManifestError without problems"
    return problems


def codes(problems: list[ManifestProblem]) -> list[str]:
    return [p.code for p in problems]


def call_main(main: Callable[[list[str]], int], argv: list[str], capsys) -> tuple[int, str]:
    """Run a CLI ``main(argv)``; returns (exit code, stdout + stderr)."""
    capsys.readouterr()
    try:
        rc = main(argv)
    except SystemExit as exc:  # argparse errors exit through SystemExit
        rc = exc.code if isinstance(exc.code, int) else 1
    out = capsys.readouterr()
    return rc, out.out + out.err


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


def run_module_bytes(module: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=cwd,
        capture_output=True,
        timeout=300,
        env=_env(),
        check=False,
    )


def split_cli(
    dataset: Path, splits: Path, capsys, *extra: str, registry: Path | None = None
) -> tuple[int, str]:
    argv = ["--dataset-dir", str(dataset), "--splits-dir", str(splits), "--seed", "42"]
    if registry is not None:
        argv += ["--external-sources", str(registry)]
    return call_main(split_mod.main, [*argv, *extra], capsys)


def read_split_csv(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["image_path"]: r["split"] for r in csv.DictReader(fh)}


def item_of(image_path: str) -> str:
    return Path(image_path).name.split("__")[0]


def tree_snapshot(path: Path) -> dict[str, bytes]:
    if not path.exists():
        return {}
    return {
        p.relative_to(path).as_posix(): p.read_bytes()
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def write_hash(splits: Path, name: str) -> None:
    body = (splits / f"{name}.csv").read_bytes()
    (splits / f"{name}.sha256").write_text(
        f"{hashlib.sha256(body).hexdigest()}  {name}.csv\n", encoding="utf-8"
    )


def n_external_images(meta: dict[str, Any]) -> dict[str, int]:
    """``n_external_images`` per split, wherever the split counts live in ``split_v<N>.json``."""
    counts = meta.get("counts", {})
    if isinstance(counts.get("n_external_images"), dict):
        return {w: counts["n_external_images"][w] for w in SPLITS}
    if all(isinstance(counts.get(w), dict) for w in SPLITS):
        return {w: counts[w]["n_external_images"] for w in SPLITS}
    raise AssertionError(f"n_external_images not found in the split counts: {meta}")


def copy_template(template: Path, tmp_path: Path, name: str = "ds") -> Path:
    return Path(shutil.copytree(template, _inside(tmp_path / name, tmp_path)))


def reg(root: Path) -> Path:
    return root / "external_sources.csv"


# --------------------------------------------------------------------------------------------
# Templates (generated once per module, copied per test)
# --------------------------------------------------------------------------------------------


def _gen(factory: pytest.TempPathFactory, name: str, **kwargs: Any) -> Path:
    return make_synthetic_dataset(factory.mktemp(name) / "ds", **kwargs)


@pytest.fixture(scope="module")
def _t42_plain(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _gen(tmp_path_factory, "s035_42_plain")


@pytest.fixture(scope="module")
def _t42_mixed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _gen(
        tmp_path_factory,
        "s035_42_mixed",
        contributor_items_per_stratum=1,
        external_items_per_stratum=1,
    )


@pytest.fixture(scope="module")
def _t203_plain(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _gen(tmp_path_factory, "s035_203_plain", items_per_stratum=20, images_per_item=3)


@pytest.fixture(scope="module")
def _t203_e1(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _gen(
        tmp_path_factory,
        "s035_203_e1",
        items_per_stratum=20,
        images_per_item=3,
        external_items_per_stratum=1,
    )


@pytest.fixture(scope="module")
def _t203_e2(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _gen(
        tmp_path_factory,
        "s035_203_e2",
        items_per_stratum=20,
        images_per_item=3,
        external_items_per_stratum=2,
    )


@pytest.fixture
def ds_plain(_t42_plain: Path, tmp_path: Path) -> Path:
    """Dataset 4/2 without contributor or external images (88 rows)."""
    return copy_template(_t42_plain, tmp_path)


@pytest.fixture
def ds_mixed(_t42_mixed: Path, tmp_path: Path) -> Path:
    """The CA-02 dataset: 4/2 with 1 contributor and 1 external item per stratum (121 rows)."""
    return copy_template(_t42_mixed, tmp_path)


# --------------------------------------------------------------------------------------------
# CA-12 environment: thresholds + evaluate on the tiny fixture (no torch), run once per module
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _evaluated(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    root = tmp_path_factory.mktemp("s035_eval")
    dataset_dir = make_synthetic_dataset(root / "ds", external_items_per_stratum=1)
    registry = reg(dataset_dir)
    splits = root / "splits"
    argv = ["--dataset-dir", str(dataset_dir), "--splits-dir", str(splits)]
    assert split_mod.main([*argv, "--external-sources", str(registry)]) == 0
    config = {
        "model_version": TINY_VERSION,
        "dataset_dir": str(dataset_dir),
        "split_file": str(splits / "split_v1.csv"),
        "backbone": "tiny",
        "pretrained": False,
        "epochs_a": 1,
        "epochs_b_max": 1,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(root / "models"),
        "reports_root": str(root / "reports"),
        "checkpoints_root": str(root / "checkpoints"),
        "external_sources": str(registry),
    }
    config_path = root / "config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    model_dir = root / "models" / TINY_VERSION
    shutil.copytree(TINY_MODEL, model_dir)
    assert thresholds_mod.main(["--config", str(config_path)]) == 0
    assert evaluate_mod.main(["--config", str(config_path)]) == 0
    return SimpleNamespace(
        root=root, dataset_dir=dataset_dir, registry=registry, model_dir=model_dir, config=config
    )


@pytest.fixture
def model_env(_evaluated: SimpleNamespace, tmp_path: Path) -> SimpleNamespace:
    """A per-test copy of the CA-12 model directory (``model.sha256`` + ``metrics.json``) and of
    the synthetic registry."""
    model_dir = copy_template(_evaluated.model_dir, tmp_path, "model")
    registry = _inside(tmp_path / "external_sources.csv", tmp_path)
    shutil.copyfile(_evaluated.registry, registry)
    return SimpleNamespace(
        model_dir=model_dir,
        registry=registry,
        metrics_path=model_dir / "metrics.json",
        root=tmp_path,
    )


def load_metrics(env: SimpleNamespace) -> dict[str, Any]:
    return json.loads(env.metrics_path.read_text(encoding="utf-8"))


def save_metrics(env: SimpleNamespace, metrics: dict[str, Any]) -> None:
    _inside(env.metrics_path, env.root)
    env.metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def release_notes(
    env: SimpleNamespace, *, output: Path | None = None, registry: Path | None = None
) -> subprocess.CompletedProcess[str]:
    args = ["release-notes", "--model-dir", str(env.model_dir)]
    args += ["--external-sources", str(registry or env.registry)]
    if output is not None:
        args += ["--output", str(output)]
    return run_module("qc_ml.report", args, env.root)


def changelog(
    env: SimpleNamespace, registry: Path | None = None
) -> subprocess.CompletedProcess[str]:
    args = ["changelog", "--model-dir", str(env.model_dir)]
    args += ["--external-sources", str(registry or env.registry)]
    return run_module("qc_ml.report", args, env.root)


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


# --------------------------------------------------------------------------------------------
# CA-01 item_id of external images
# --------------------------------------------------------------------------------------------


def test_ca01_item_id_pattern_and_helpers() -> None:
    for good in ("S-012", "O-500", "XS-0001", "XN-9999", "XO-0042"):
        assert ITEM_ID_PATTERN.fullmatch(good), good
    for bad in (
        "XS-001",
        "XS-00001",
        "X-0001",
        "XX-0001",
        "xS-0001",
        "SX-0001",
        "XS-0001\n",
        "XS-０００１",
    ):
        assert not ITEM_ID_PATTERN.fullmatch(bad), repr(bad)
    assert is_external_item("XN-0002") is True
    assert is_external_item("N-002") is False
    assert item_type_letter("XO-0042") == "O"
    assert split_mod.ITEM_ID_PATTERN is data_mod.ITEM_ID_PATTERN
    match = split_mod.IMAGE_FILE_PATTERN.fullmatch("XS-0001__0__20261022T141503Z.jpg")
    assert match is not None and match.group(1) == "XS-0001"
    assert split_mod.IMAGE_FILE_PATTERN.fullmatch("XS-001__0__20261022T141503Z.jpg") is None


# --------------------------------------------------------------------------------------------
# CA-02 / CA-03 origin columns
# --------------------------------------------------------------------------------------------


def test_ca02_origin_columns(ds_mixed: Path) -> None:
    df = load_manifest(ds_mixed, external_sources=reg(ds_mixed))
    assert len(df) == 121
    assert df["origin"].value_counts().to_dict() == {
        "capture": 88,
        "contributor": 22,
        "external": 11,
    }
    contrib = df["origin"] == "contributor"
    external = df["origin"] == "external"
    assert (df.loc[contrib, "contributor"] == "c01").all()
    assert df.loc[~contrib, "contributor"].map(lambda v: v is None).all()
    assert (df.loc[external, "source_id"] == "synthetic").all()
    assert df.loc[~external, "source_id"].map(lambda v: v is None).all()
    assert df.attrs["sources_sha256"] == sha256_file(ds_mixed / "sources.csv")
    # origin external is exactly the external item_ids
    assert set(df.loc[external, "item_id"]) == {i for i in df["item_id"] if is_external_item(i)}


def test_ca03_compatibility_without_sources(ds_plain: Path, tmp_path: Path) -> None:
    assert not (ds_plain / "sources.csv").exists()
    df = load_manifest(ds_plain, external_sources=tmp_path / "does-not-exist.csv")
    assert len(df) == 88
    assert (df["origin"] == "capture").all()
    assert df["contributor"].map(lambda v: v is None).all()
    assert df["source_id"].map(lambda v: v is None).all()
    assert df.attrs["sources_sha256"] is None
    assert df.attrs["external_sources_sha256"] is None


# --------------------------------------------------------------------------------------------
# CA-04 sources.csv problems (one test per case)
# --------------------------------------------------------------------------------------------


def _first(rows: list[dict[str, str]], origin: str, prefix: str | None = None) -> dict[str, str]:
    for row in rows:
        if row["origin"] == origin and (
            prefix is None or item_of(row["image_path"]).startswith(prefix)
        ):
            return row
    raise AssertionError(f"no {origin} row with prefix {prefix}")


def _case_unknown_source_id(root: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    _first(rows, "external")["source_id"] = "desconhecida"
    return rows


def _case_empty_source_ref(root: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    _first(rows, "external")["source_ref"] = ""
    return rows


def _case_bidi_source_ref(root: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    row = _first(rows, "external")
    row["source_ref"] = "synthetic/‮XS.png"
    return rows


def _case_upper_contributor(root: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    _first(rows, "contributor")["contributor"] = "C01"
    return rows


def _case_contributor_with_source(root: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    _first(rows, "contributor")["source_id"] = "synthetic"
    return rows


def _case_origin_capture(root: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    _first(rows, "contributor")["origin"] = "capture"
    return rows


def _case_sha_63(root: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    row = _first(rows, "contributor")
    row["input_sha256"] = row["input_sha256"][:63]
    return rows


def _case_duplicate_input(root: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    contributors = [r for r in rows if r["origin"] == "contributor"]
    contributors[1]["input_sha256"] = contributors[0]["input_sha256"]
    return rows


def _case_duplicate_row(root: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    copy = dict(_first(rows, "contributor"))
    copy["input_sha256"] = new_sha("dup-row")
    return [*rows, copy]


def _case_unknown_image(root: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    extra = {
        "image_path": "raw/screw/fair/S-999__0__20261101T100000Z.jpg",
        "origin": "contributor",
        "contributor": "c01",
        "source_id": "",
        "source_ref": "",
        "input_sha256": new_sha("unknown-image"),
    }
    return [*rows, extra]


def _case_missing_source(root: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [r for r in rows if item_of(r["image_path"]) != "XS-0001"]


def _case_own_image_external(root: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    own = next(r["image_path"] for r in read_rows(root) if r["item_id"] == "S-001")
    extra = {
        "image_path": own,
        "origin": "external",
        "contributor": "",
        "source_id": "synthetic",
        "source_ref": "synthetic/S-001.png",
        "input_sha256": new_sha("own-external"),
    }
    return [*rows, extra]


SOURCES_CASES = [
    ("unknown_source_id", _case_unknown_source_id),
    ("empty_source_ref", _case_empty_source_ref),
    ("bidi_source_ref", _case_bidi_source_ref),
    ("upper_contributor", _case_upper_contributor),
    ("contributor_with_source", _case_contributor_with_source),
    ("origin_capture", _case_origin_capture),
    ("sha_63", _case_sha_63),
    ("duplicate_input", _case_duplicate_input),
    ("duplicate_row", _case_duplicate_row),
    ("unknown_image", _case_unknown_image),
    ("missing_source", _case_missing_source),
    ("own_image_external", _case_own_image_external),
]
SOURCES_EXPECTED = {
    "unknown_source_id": "unknown_source_id",
    "empty_source_ref": "invalid_source_ref",
    "bidi_source_ref": "invalid_source_ref",
    "upper_contributor": "invalid_contributor",
    "contributor_with_source": "source_fields_mismatch",
    "origin_capture": "invalid_origin",
    "sha_63": "invalid_input_sha256",
    "duplicate_input": "duplicate_input",
    "duplicate_row": "duplicate_source_row",
    "unknown_image": "source_unknown_image",
    "missing_source": "missing_source",
    "own_image_external": "external_item_mismatch",
}


@pytest.mark.parametrize(("case", "edit"), SOURCES_CASES, ids=[c for c, _ in SOURCES_CASES])
def test_ca04_sources_problems(ds_mixed: Path, case: str, edit) -> None:
    rows = edit(ds_mixed, read_sources(ds_mixed))
    write_sources(ds_mixed, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_mixed, external_sources=reg(ds_mixed))
    problems = problems_of(excinfo)
    expected = SOURCES_EXPECTED[case]
    assert expected in codes(problems), (case, [str(p) for p in problems])
    if expected != "missing_source":
        assert all(p.file == "sources.csv" for p in problems if p.code == expected), problems


def test_ca04_sources_missing_column(ds_mixed: Path) -> None:
    rows = read_sources(ds_mixed)
    header = [c for c in SOURCES_HEADER if c != "input_sha256"]
    write_sources(ds_mixed, rows, header)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_mixed, external_sources=reg(ds_mixed))
    problems = problems_of(excinfo)
    assert "missing_column" in codes(problems), [str(p) for p in problems]
    assert any(p.file == "sources.csv" for p in problems if p.code == "missing_column")


def test_ca04_validate_cli_counts_missing_source(ds_mixed: Path) -> None:
    write_sources(ds_mixed, _case_missing_source(ds_mixed, read_sources(ds_mixed)))
    args = ["validate", "--dataset-dir", str(ds_mixed), "--external-sources", str(reg(ds_mixed))]
    proc = run_module("qc_ml.data", args, ds_mixed.parent)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "count missing_source: 1" in proc.stdout + proc.stderr


# --------------------------------------------------------------------------------------------
# CA-05 registry problems
# --------------------------------------------------------------------------------------------


REGISTRY_CASES = [
    ("license_nd", {"license": "CC-BY-ND-4.0"}, "invalid_license"),
    ("license_unknown", {"license": "unknown"}, "invalid_license"),
    ("license_empty", {"license": ""}, "invalid_license"),
    ("license_nc_sa", {"license": "CC-BY-NC-SA-4.0"}, "invalid_license"),
    ("license_sa", {"license": "CC-BY-SA-4.0"}, "invalid_license"),
    ("license_nc", {"license": "CC-BY-NC-4.0"}, "invalid_license"),
    ("url_http", {"url": "http://example.org/x"}, "invalid_url"),
    ("date_feb30", {"retrieved_at": "2026-02-30"}, "invalid_date"),
    ("source_id_upper", {"source_id": "Synthetic"}, "invalid_source_id"),
    ("attribution_newline", {"attribution": "Synthetic\ntest images"}, "invalid_text"),
]


@pytest.mark.parametrize(
    ("change", "expected"),
    [(c, e) for _, c, e in REGISTRY_CASES],
    ids=[name for name, _, _ in REGISTRY_CASES],
)
def test_ca05_registry_problems(ds_mixed: Path, change: dict[str, str], expected: str) -> None:
    write_registry(reg(ds_mixed), [{**SYNTHETIC_SOURCE, **change}])
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_mixed, external_sources=reg(ds_mixed))
    problems = problems_of(excinfo)
    hits = [p for p in problems if p.code == expected]
    assert hits, [str(p) for p in problems]
    assert all(p.file == "external_sources.csv" for p in hits), hits


def test_ca05_registry_duplicate_source_id(ds_mixed: Path) -> None:
    write_registry(reg(ds_mixed), [SYNTHETIC_SOURCE, SYNTHETIC_SOURCE])
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_mixed, external_sources=reg(ds_mixed))
    hits = [p for p in problems_of(excinfo) if p.code == "duplicate_source_id"]
    assert hits and all(p.file == "external_sources.csv" for p in hits)


def test_ca05_header_only_registry_without_externals(ds_plain: Path) -> None:
    registry = write_registry(ds_plain / "external_sources.csv", [])
    df = load_manifest(ds_plain, external_sources=registry)
    assert len(df) == 88


# --------------------------------------------------------------------------------------------
# CA-06 exclusion of an external image (R-14)
# --------------------------------------------------------------------------------------------


def test_ca06_excluded_external_image(ds_mixed: Path) -> None:
    victim = next(r["image_path"] for r in read_rows(ds_mixed) if r["item_id"] == "XS-0001")
    (_inside(ds_mixed / victim, ds_mixed)).unlink()
    write_csv(ds_mixed / "exclusions.csv", ["image_path", "reason"], [[victim, "other"]])
    df = load_manifest(ds_mixed, external_sources=reg(ds_mixed))
    assert len(df) == 120
    assert not (df["item_id"] == "XS-0001").any()


# --------------------------------------------------------------------------------------------
# CA-07 to CA-10 split
# --------------------------------------------------------------------------------------------


def test_ca07_externals_in_train_and_own_split_unchanged(_t203_e2: Path, tmp_path: Path) -> None:
    ds = copy_template(_t203_e2, tmp_path)
    df = load_manifest(ds, external_sources=reg(ds))
    frame = make_split(df, seed=42).frame
    mapping = dict(zip(frame["image_path"], frame["split"], strict=True))
    ext_mask = df["item_id"].map(is_external_item)
    ext_paths = list(df.loc[ext_mask, "image_path"])
    assert len(ext_paths) == 22
    assert all(mapping[p] == "train" for p in ext_paths)

    merged = df[~ext_mask].merge(frame, on="image_path")
    items = merged.groupby("item_id").agg(
        object_type=("object_type", "first"),
        grade=("grade", "first"),
        split=("split", "first"),
    )
    items["grade"] = items["grade"].fillna("none")
    strata = items.groupby(["object_type", "grade"])
    assert len(strata) == 11
    for name, group in strata:
        assert group["split"].value_counts().to_dict() == {"train": 14, "val": 3, "test": 3}, name

    own = make_split(df[~ext_mask], seed=42).frame
    own_map = dict(zip(own["image_path"], own["split"], strict=True))
    assert {p: w for p, w in mapping.items() if p not in set(ext_paths)} == own_map


EXTERNAL_PLAN = [
    *[(f"XS-{k:04d}", "screw", g) for k, g in enumerate(GRADES, start=1)],
    *[(f"XN-{k:04d}", "nut", g) for k, g in enumerate(GRADES, start=1)],
    ("XO-0001", "other", None),
]


def add_externals(root: Path) -> list[str]:
    """Add the 11 CA-08 external images (manifest row, sources.csv row, file on disk) and the
    synthetic registry of §4.7."""
    sources = read_sources(root) if (root / "sources.csv").exists() else []
    added = []
    for k, (item_id, object_type, grade) in enumerate(EXTERNAL_PLAN):
        rel = add_image(root, item_id, object_type, grade, 0, f"20261105T12{k:02d}00Z")
        sources.append(
            {
                "image_path": rel,
                "origin": "external",
                "contributor": "",
                "source_id": "synthetic",
                "source_ref": f"synthetic/{item_id}.png",
                "input_sha256": sha256_file(root / rel),
            }
        )
        added.append(rel)
    write_sources(root, sources)
    write_registry(reg(root), [SYNTHETIC_SOURCE])
    return added


def test_ca08_new_externals_go_to_train(_t203_plain: Path, tmp_path: Path, capsys) -> None:
    ds = copy_template(_t203_plain, tmp_path)
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    v1 = read_split_csv(splits / "split_v1.csv")
    added = add_externals(ds)
    assert len(added) == 11

    rc, out = split_cli(ds, splits, capsys, registry=reg(ds))
    assert rc == 0, out
    assert (splits / "split_v2.csv").exists()
    v2 = read_split_csv(splits / "split_v2.csv")
    assert all(v2[p] == "train" for p in added)
    for path, which in v1.items():
        assert v2[path] == which, path
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    assert n_external_images(meta) == {"train": 11, "val": 0, "test": 0}


@pytest.fixture
def ca09_state(_t203_e1: Path, tmp_path: Path, capsys) -> SimpleNamespace:
    ds = copy_template(_t203_e1, tmp_path)
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys, registry=reg(ds))
    assert rc == 0, out
    df = load_manifest(ds, external_sources=reg(ds))
    original = load_split(splits / "split_v1.csv")
    victim = next(r["image_path"] for r in read_rows(ds) if r["item_id"] == "XS-0001")
    return SimpleNamespace(ds=ds, splits=splits, df=df, original=original, victim=victim)


def _edit_split_file(splits: Path, victim: str, which: str) -> None:
    path = splits / "split_v1.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    header, body = rows[0], rows[1:]
    idx_path, idx_split = header.index("image_path"), header.index("split")
    hit = 0
    for row in body:
        if row[idx_path] == victim:
            row[idx_split] = which
            hit += 1
    assert hit == 1
    write_csv(path, header, body)
    write_hash(splits, "split_v1")


def test_ca09_external_never_in_val_or_test(ca09_state: SimpleNamespace, capsys) -> None:
    st = ca09_state
    # (a) CLI with the split_v1 edited (external image in test) and a new item to write
    _edit_split_file(st.splits, st.victim, "test")
    edited = load_split(st.splits / "split_v1.csv")  # the rewritten hash is accepted
    add_image(st.ds, "S-301", "screw", "fair", 0, "20261106T100000Z")
    add_image(st.ds, "S-301", "screw", "fair", 1, "20261106T100100Z")
    before = tree_snapshot(st.splits)
    rc, out = split_cli(st.ds, st.splits, capsys, registry=reg(st.ds))
    assert rc == 2, out
    assert "XS-0001" in out
    assert tree_snapshot(st.splits) == before

    # (b) make_split with the edited previous
    with pytest.raises(SplitIntegrityError, match="XS-0001"):
        make_split(st.df, seed=42, previous=edited)

    # (c) rows_for guard in test and in val
    with pytest.raises(SplitIntegrityError, match="XS-0001"):
        rows_for(st.df, edited, "test")
    in_val = st.original.copy()
    in_val.loc[in_val["image_path"] == st.victim, "split"] = "val"
    with pytest.raises(SplitIntegrityError, match="XS-0001"):
        rows_for(st.df, in_val, "val")

    train = rows_for(st.df, st.original, "train")
    ext_train = [i for i in train["item_id"] if is_external_item(i)]
    assert len(ext_train) == 11


def _gen_ext(tmp_path: Path, k: int) -> Path:
    return make_synthetic_dataset(
        _inside(tmp_path / f"ds{k}", tmp_path),
        items_per_stratum=20,
        images_per_item=3,
        external_items_per_stratum=k,
    )


def test_ca10_external_fraction_ceiling(tmp_path: Path, capsys) -> None:
    ds18 = _gen_ext(tmp_path, 18)
    splits = tmp_path / "splits18"
    splits.mkdir()
    rc, out = split_cli(ds18, splits, capsys, registry=reg(ds18))
    assert rc == 0, out
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["max_external_fraction"] == 0.3
    assert meta["external_fraction_train"] == 0.3

    ds19 = _gen_ext(tmp_path, 19)
    splits19 = tmp_path / "splits19"
    splits19.mkdir()
    rc, out = split_cli(ds19, splits19, capsys, registry=reg(ds19))
    assert rc == 2, out
    assert "external fraction" in out and "209/671" in out, out
    assert tree_snapshot(splits19) == {}

    for bad in ("0", "1.5", "abc"):
        rc, out = split_cli(
            ds19, splits19, capsys, "--max-external-fraction", bad, registry=reg(ds19)
        )
        assert rc == 2, (bad, out)
        assert tree_snapshot(splits19) == {}, bad

    rc, out = split_cli(
        ds19, splits19, capsys, "--max-external-fraction", "0.35", registry=reg(ds19)
    )
    assert rc == 0, out
    assert (splits19 / "split_v1.csv").exists()


# --------------------------------------------------------------------------------------------
# CA-11 data report
# --------------------------------------------------------------------------------------------


def test_ca11_data_report_by_origin(tmp_path: Path, capsys) -> None:
    ds = make_synthetic_dataset(
        _inside(tmp_path / "ds", tmp_path),
        items_per_stratum=20,
        images_per_item=3,
        contributor_items_per_stratum=1,
        external_items_per_stratum=2,
    )
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys, registry=reg(ds))
    assert rc == 0, out
    out_file = tmp_path / "reports" / "data_report.json"
    argv = [
        "report",
        "--dataset-dir",
        str(ds),
        "--external-sources",
        str(reg(ds)),
        "--split",
        str(splits / "split_v1.csv"),
        "--out",
        str(out_file),
    ]
    rc, out = call_main(data_mod.main, argv, capsys)
    assert rc == 0, out
    report = json.loads(out_file.read_text(encoding="utf-8"))
    assert set(report) >= REPORT_KEYS_011 | REPORT_KEYS_035
    by_origin = report["counts_by_origin"]
    assert set(by_origin) == set(ORIGINS)
    assert (by_origin["capture"]["n_images"], by_origin["capture"]["n_items"]) == (660, 220)
    assert (by_origin["contributor"]["n_images"], by_origin["contributor"]["n_items"]) == (33, 11)
    assert (by_origin["external"]["n_images"], by_origin["external"]["n_items"]) == (22, 22)
    assert by_origin["external"]["by_split"] == {"train": 22, "val": 0, "test": 0}
    for origin in ORIGINS:
        assert set(by_origin[origin]["by_split"]) == set(SPLITS)
        assert sum(by_origin[origin]["by_split"].values()) == by_origin[origin]["n_images"]
    assert report["n_contributors"] == 1
    assert report["by_source"] == {"synthetic": 22}
    assert report["items_per_grade"]["screw"]["perfect"] == 21
    assert len(report["below_target"]) == 10
    combos = {(e["object_type"], e["grade"]) for e in report["below_target"]}
    assert combos == {(t, g) for t in ("screw", "nut") for g in GRADES}
    for entry in report["below_target"]:
        assert entry["n_images"] == 63 and entry["n_items"] == 21, entry
    assert report["below_minimum"] == []
    assert report["external_fraction_train"] == pytest.approx(22 / 517, abs=1e-12)
    # n_images / n_items keep counting every image
    assert report["n_images"] == 715
    assert report["n_items"] == 253
    assert "c01" not in json.dumps(report)  # never the contributor codes


# --------------------------------------------------------------------------------------------
# CA-12 metrics.json
# --------------------------------------------------------------------------------------------


def test_ca12_metrics_counts_by_origin(_evaluated: SimpleNamespace) -> None:
    metrics = json.loads((_evaluated.model_dir / "metrics.json").read_text(encoding="utf-8"))
    # SPEC-016 section 4.8: new top-level key tool_grade_metrics.
    assert set(metrics) == METRIC_KEYS | {"tool_grade_metrics"}
    counts = metrics["counts"]
    assert counts["train"]["by_origin"] == {"capture": 44, "contributor": 0, "external": 11}
    assert counts["val"]["by_origin"]["external"] == 0
    assert counts["test"]["by_origin"]["external"] == 0
    for which in SPLITS:
        assert set(counts[which]["by_origin"]) == set(ORIGINS)
    assert counts["train"]["by_source"] == {"synthetic": 11}
    assert counts["val"]["by_source"] == {}
    assert counts["test"]["by_source"] == {}


# --------------------------------------------------------------------------------------------
# CA-13 CHANGELOG
# --------------------------------------------------------------------------------------------


def test_ca13_changelog_data_section(model_env: SimpleNamespace) -> None:
    proc = changelog(model_env)
    assert proc.returncode == 0, proc.stderr
    entry = proc.stdout
    lines = entry.splitlines()
    assert "### Dados" in lines
    assert "- Validação e teste: 0 e 0 imagens externas (ADR-020)." in lines
    assert "- Treino: 11 imagens externas de 55 (0,2000)." in lines
    assert SYNTH_DATA_LINE in lines
    # the section comes after the metrics table
    first_table = next(i for i, ln in enumerate(lines) if ln.lstrip().startswith("|"))
    assert lines.index("### Dados") > first_table

    header_only = write_registry(model_env.root / "header_only.csv", [])
    proc = changelog(model_env, header_only)
    assert proc.returncode == 0, proc.stderr
    src = source_lines(data_section(proc.stdout))
    assert len(src) == 1 and src[0].startswith("- `synthetic`: 11 imagens"), src
    assert src[0].endswith("licença não encontrada no registro"), src

    metrics = load_metrics(model_env)
    for which in SPLITS:
        metrics["counts"][which].pop("by_origin", None)
    save_metrics(model_env, metrics)
    proc = changelog(model_env)
    assert proc.returncode == 0, proc.stderr
    assert "### Dados" not in proc.stdout


# --------------------------------------------------------------------------------------------
# CA-14 / CA-15 repository registry and generator
# --------------------------------------------------------------------------------------------


def test_ca14_repository_registry() -> None:
    path = ML_ROOT / "external_sources.csv"
    first = path.read_bytes().split(b"\n", 1)[0]
    assert first == b"source_id,title,url,license,license_url,attribution,retrieved_at"
    load_external_sources(path)
    proc = subprocess.run(
        ["git", "check-ignore", "ml/external_sources.csv"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert path.resolve() == data_mod.DEFAULT_EXTERNAL_SOURCES


def test_ca15_generator_defaults_unchanged(tmp_path: Path) -> None:
    a = make_synthetic_dataset(_inside(tmp_path / "a", tmp_path))
    b = make_synthetic_dataset(
        _inside(tmp_path / "b", tmp_path),
        external_items_per_stratum=0,
        contributor_items_per_stratum=0,
    )
    snap_a, snap_b = tree_snapshot(Path(a)), tree_snapshot(Path(b))
    assert snap_a and snap_a == snap_b
    for snap in (snap_a, snap_b):
        assert "sources.csv" not in snap
        assert "external_sources.csv" not in snap


# --------------------------------------------------------------------------------------------
# CA-16 to CA-19 release notes
# --------------------------------------------------------------------------------------------


def test_ca16_release_notes_with_source(model_env: SimpleNamespace) -> None:
    notes = model_env.root / "notes.md"
    proc = release_notes(model_env, output=notes)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    raw = notes.read_bytes()
    text = raw.decode("utf-8")
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert text.endswith("\n") and not text.endswith("\n\n")
    lines = text.split("\n")
    sha = (model_env.model_dir / "model.sha256").read_text(encoding="utf-8").rstrip("\n")
    assert lines[0] == f"sha256: {sha}"
    i_title = lines.index(NOTES_TITLE)
    src = [ln for ln in lines if ln.startswith("- `")]
    assert src == [SYNTH_NOTES_LINE]
    i_src = lines.index(SYNTH_NOTES_LINE)
    i_paths = lines.index(PATHS_LINE)
    assert 0 < i_title < i_src < i_paths
    assert "não usa imagens externas" not in text

    cl = changelog(model_env)
    assert cl.returncode == 0, cl.stderr
    cl_src = source_lines(data_section(cl.stdout))
    assert len(cl_src) == 1 and SYNTH_NOTES_LINE.startswith(cl_src[0]), cl_src

    args = ["release-notes", "--model-dir", str(model_env.model_dir)]
    args += ["--external-sources", str(model_env.registry)]
    out = run_module_bytes("qc_ml.report", args, model_env.root)
    assert out.returncode == 0, out.stderr
    assert out.stdout == raw


def _notes_fail(env: SimpleNamespace, notes: Path, registry: Path | None = None) -> str:
    proc = release_notes(env, output=notes, registry=registry)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stdout == ""
    return proc.stderr


def test_ca17_source_not_in_registry_blocks(model_env: SimpleNamespace) -> None:
    metrics = load_metrics(model_env)
    metrics["counts"]["train"]["by_source"] = {"zz-fora": 2, "synthetic": 11}
    save_metrics(model_env, metrics)
    notes = model_env.root / "notes.md"

    # (a) without the output file
    err = _notes_fail(model_env, notes)
    assert "source not in registry: zz-fora" in err
    assert "source not in registry: synthetic" not in err
    assert not notes.exists()

    # (b) with an existing output file
    notes.write_text("antigo\n", encoding="utf-8")
    err = _notes_fail(model_env, notes)
    assert "source not in registry: zz-fora" in err
    assert "source not in registry: synthetic" not in err
    assert notes.read_bytes() == b"antigo\n"

    # the changelog only marks the line
    cl = changelog(model_env)
    assert cl.returncode == 0, cl.stderr
    assert "- `zz-fora`: 2 imagens, licença não encontrada no registro" in cl.stdout.splitlines()


def test_ca17_header_only_registry_blocks(model_env: SimpleNamespace) -> None:
    header_only = write_registry(model_env.root / "header_only.csv", [])
    notes = model_env.root / "notes.md"
    err = _notes_fail(model_env, notes, header_only)
    assert "source not in registry: synthetic" in err
    assert not notes.exists()


def test_ca17_invalid_source_id_not_echoed(model_env: SimpleNamespace) -> None:
    marker = f"mk{uuid.uuid4().hex}"
    metrics = load_metrics(model_env)
    metrics["counts"]["train"]["by_source"] = {f"bad{marker}‮": 1, "synthetic": 11}
    save_metrics(model_env, metrics)
    notes = model_env.root / "notes.md"
    err = _notes_fail(model_env, notes)
    assert "source not in registry: <invalid source_id>" in err
    assert marker not in err
    assert not notes.exists()


def test_ca17_order_of_two_sources(model_env: SimpleNamespace) -> None:
    write_registry(model_env.registry, [SYNTHETIC_SOURCE, AA_SOURCE])
    metrics = load_metrics(model_env)
    metrics["counts"]["train"]["by_source"] = {"synthetic": 11, "aa-fonte": 2}
    save_metrics(model_env, metrics)
    notes = model_env.root / "notes.md"
    proc = release_notes(model_env, output=notes)
    assert proc.returncode == 0, proc.stderr
    src = [ln for ln in notes.read_text(encoding="utf-8").split("\n") if ln.startswith("- `")]
    assert src == [AA_NOTES_LINE, SYNTH_NOTES_LINE]
    cl = changelog(model_env)
    assert cl.returncode == 0, cl.stderr
    cl_src = source_lines(data_section(cl.stdout))
    assert len(cl_src) == 2, cl_src
    for note_line, cl_line in zip(src, cl_src, strict=True):
        assert note_line.startswith(cl_line), (note_line, cl_line)


def _no_external_metrics(metrics: dict[str, Any], case: str) -> dict[str, Any]:
    for which in SPLITS:
        counts = metrics["counts"][which]
        if case == "empty":
            counts["by_source"] = {}
            counts["by_origin"]["external"] = 0
        else:
            counts.pop("by_origin", None)
            counts.pop("by_source", None)
    return metrics


@pytest.mark.parametrize("case", ["empty", "old_metrics"])
def test_ca18_release_notes_without_externals(model_env: SimpleNamespace, case: str) -> None:
    save_metrics(model_env, _no_external_metrics(load_metrics(model_env), case))
    notes = model_env.root / "notes.md"
    proc = release_notes(model_env, output=notes)
    assert proc.returncode == 0, proc.stderr
    lines = notes.read_text(encoding="utf-8").split("\n")
    sha = (model_env.model_dir / "model.sha256").read_text(encoding="utf-8").rstrip("\n")
    assert f"sha256: {sha}" in lines
    assert NOTES_TITLE in lines
    assert NO_EXTERNAL_LINE in lines
    assert PATHS_LINE in lines
    assert not [ln for ln in lines if ln.startswith("- `")]


def _break_sha_missing(env: SimpleNamespace) -> None:
    (_inside(env.model_dir / "model.sha256", env.root)).unlink()


def _break_sha_63(env: SimpleNamespace) -> None:
    path = _inside(env.model_dir / "model.sha256", env.root)
    path.write_text(path.read_text(encoding="utf-8")[:63] + "\n", encoding="utf-8")


def _break_metrics_missing(env: SimpleNamespace) -> None:
    (_inside(env.metrics_path, env.root)).unlink()


def _break_metrics_invalid(env: SimpleNamespace) -> None:
    _inside(env.metrics_path, env.root).write_text('{"counts": ', encoding="utf-8")


def _break_registry_nc(env: SimpleNamespace) -> None:
    write_registry(env.registry, [{**SYNTHETIC_SOURCE, "license": "CC-BY-NC-4.0"}])


ERROR_CASES = [
    ("sha_missing", _break_sha_missing),
    ("sha_63", _break_sha_63),
    ("metrics_missing", _break_metrics_missing),
    ("metrics_invalid", _break_metrics_invalid),
    ("registry_nc", _break_registry_nc),
]


@pytest.mark.parametrize(("case", "breaker"), ERROR_CASES, ids=[c for c, _ in ERROR_CASES])
def test_ca19_release_notes_errors(model_env: SimpleNamespace, case: str, breaker) -> None:
    breaker(model_env)
    notes = model_env.root / "notes.md"
    _notes_fail(model_env, notes)
    assert not notes.exists()


def test_ca19_existing_output_kept_on_error(model_env: SimpleNamespace) -> None:
    _break_sha_missing(model_env)
    notes = model_env.root / "notes.md"
    notes.write_text("antigo\n", encoding="utf-8")
    _notes_fail(model_env, notes)
    assert notes.read_bytes() == b"antigo\n"


# --------------------------------------------------------------------------------------------
# CA-20 README
# --------------------------------------------------------------------------------------------


def _markdown_section(text: str, needle: str) -> str:
    lines = text.splitlines()
    in_fence = False
    start, level = None, 0
    out: list[str] = []
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        heading = None if in_fence else re.match(r"^(#{1,6})\s", line)
        if start is None:
            if heading and needle in line:
                start, level = True, len(heading.group(1))
                out.append(line)
            continue
        if heading and len(heading.group(1)) <= level:
            break
        out.append(line)
    assert start, f"no heading with {needle!r}"
    return "\n".join(out)


def test_ca20_readme_section() -> None:
    section = _markdown_section(
        (ML_ROOT / "README.md").read_text(encoding="utf-8"), "Origem das imagens"
    )
    for needle in (
        "ml/external_sources.csv",
        "--max-external-fraction",
        "qc_ml.report release-notes",
        "--notes-file",
        "source not in registry",
    ):
        assert needle in section, needle


# --------------------------------------------------------------------------------------------
# Exploratory (no CA): edge cases around the SPEC
# --------------------------------------------------------------------------------------------


def test_extra_external_without_registry_is_unknown_source_id(
    ds_mixed: Path, tmp_path: Path
) -> None:
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_mixed, external_sources=tmp_path / "absent.csv")
    problems = problems_of(excinfo)
    hits = [p for p in problems if p.code == "unknown_source_id"]
    assert len(hits) == 11, [str(p) for p in problems]


def test_extra_registry_validated_even_when_unused(ds_plain: Path) -> None:
    registry = write_registry(
        ds_plain / "external_sources.csv", [{**SYNTHETIC_SOURCE, "license": "CC-BY-SA-4.0"}]
    )
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_plain, external_sources=registry)
    assert "invalid_license" in codes(problems_of(excinfo))


@pytest.mark.parametrize(
    "license_id", ["CC0-1.0", "PDDL-1.0", "CC-BY-4.0", "MIT", "Apache-2.0", "BSD-3-Clause"]
)
def test_extra_every_allowed_license_is_accepted(tmp_path: Path, license_id: str) -> None:
    path = write_registry(tmp_path / "r.csv", [{**SYNTHETIC_SOURCE, "license": license_id}])
    loaded = load_external_sources(path)
    assert loaded["synthetic"].license == license_id
    assert str(loaded["synthetic"].retrieved_at) == "2026-10-20"


REGISTRY_EDGE = [
    ("license_lower", {"license": "cc0-1.0"}, "invalid_license"),
    ("license_space", {"license": "CC0-1.0 "}, "invalid_license"),
    ("source_id_short", {"source_id": "ab"}, "invalid_source_id"),
    ("source_id_long", {"source_id": "a" * 41}, "invalid_source_id"),
    ("source_id_dash_first", {"source_id": "-abc"}, "invalid_source_id"),
    ("title_empty", {"title": ""}, "invalid_text"),
    ("title_201", {"title": "t" * 201}, "invalid_text"),
    ("title_bidi", {"title": "abc‮"}, "invalid_text"),
    ("title_zero_width", {"title": "abc​"}, "invalid_text"),
    ("title_line_sep", {"title": "abc def"}, "invalid_text"),
    ("attribution_501", {"attribution": "a" * 501}, "invalid_text"),
    ("attribution_tab", {"attribution": "a\tb"}, "invalid_text"),
    ("url_space", {"url": "https://example.org/a b"}, "invalid_url"),
    ("url_unicode", {"url": "https://exemplo.org/ção"}, "invalid_url"),
    ("url_long", {"url": "https://" + "a" * 293}, "invalid_url"),
    ("url_short", {"url": "https://"}, "invalid_url"),
    ("license_url_http", {"license_url": "http://creativecommons.org/x"}, "invalid_url"),
    ("date_short", {"retrieved_at": "2026-1-05"}, "invalid_date"),
    ("date_full_width", {"retrieved_at": "２０２６-10-20"}, "invalid_date"),
    ("date_time", {"retrieved_at": "2026-10-20T00:00:00"}, "invalid_date"),
]


@pytest.mark.parametrize(
    ("change", "expected"),
    [(c, e) for _, c, e in REGISTRY_EDGE],
    ids=[n for n, _, _ in REGISTRY_EDGE],
)
def test_extra_registry_edge_cases(tmp_path: Path, change: dict[str, str], expected: str) -> None:
    path = write_registry(tmp_path / "r.csv", [{**SYNTHETIC_SOURCE, **change}])
    with pytest.raises(ManifestError) as excinfo:
        load_external_sources(path)
    hits = [p for p in problems_of(excinfo) if p.code == expected]
    assert hits and all(p.file == "external_sources.csv" for p in hits)


def test_extra_registry_bounds_accepted(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path / "r.csv",
        [
            {
                **SYNTHETIC_SOURCE,
                "source_id": "a" * 40,
                "title": "t" * 200,
                "attribution": "ç" * 500,
                "url": "https://" + "a" * 292,
                "license_url": "https://a",
                "retrieved_at": "2024-02-29",
            },
            {**SYNTHETIC_SOURCE, "source_id": "abc"},
        ],
    )
    loaded = load_external_sources(path)
    assert set(loaded) == {"a" * 40, "abc"}


def test_extra_registry_header_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "r.csv"
    write_csv(path, REGISTRY_HEADER[:-1], [[SYNTHETIC_SOURCE[c] for c in REGISTRY_HEADER[:-1]]])
    with pytest.raises(ManifestError) as excinfo:
        load_external_sources(path)
    assert "missing_column" in codes(problems_of(excinfo))


SOURCES_EDGE = [
    ("origin_empty", "contributor", {"origin": ""}, "invalid_origin"),
    ("origin_upper", "contributor", {"origin": "External"}, "invalid_origin"),
    ("contributor_3_digits", "contributor", {"contributor": "c001"}, "invalid_contributor"),
    ("contributor_empty", "contributor", {"contributor": ""}, "invalid_contributor"),
    ("external_with_contributor", "external", {"contributor": "c01"}, "invalid_contributor"),
    ("contributor_with_ref", "contributor", {"source_ref": "x.png"}, "source_fields_mismatch"),
    ("external_empty_source", "external", {"source_id": ""}, "unknown_source_id"),
    ("source_ref_201", "external", {"source_ref": "r" * 201}, "invalid_source_ref"),
    ("source_ref_newline", "external", {"source_ref": "a\nb"}, "invalid_source_ref"),
    ("source_ref_nul", "external", {"source_ref": "a\x00b"}, "invalid_source_ref"),
    ("source_ref_bom", "external", {"source_ref": "﻿a"}, "invalid_source_ref"),
    ("sha_upper", "contributor", {"input_sha256": "A" * 64}, "invalid_input_sha256"),
    ("sha_65", "contributor", {"input_sha256": "a" * 65}, "invalid_input_sha256"),
    ("path_absolute", "contributor", {"image_path": "/etc/passwd"}, "invalid_image_path"),
    ("path_escape", "contributor", {"image_path": "../x.jpg"}, "invalid_image_path"),
]


@pytest.mark.parametrize(
    ("origin", "change", "expected"),
    [(o, c, e) for _, o, c, e in SOURCES_EDGE],
    ids=[n for n, _, _, _ in SOURCES_EDGE],
)
def test_extra_sources_edge_cases(
    ds_mixed: Path, origin: str, change: dict[str, str], expected: str
) -> None:
    rows = read_sources(ds_mixed)
    _first(rows, origin).update(change)
    write_sources(ds_mixed, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_mixed, external_sources=reg(ds_mixed))
    assert expected in codes(problems_of(excinfo)), [str(p) for p in excinfo.value.problems]


def test_extra_source_ref_200_chars_and_unicode_accepted(ds_mixed: Path) -> None:
    rows = read_sources(ds_mixed)
    _first(rows, "external")["source_ref"] = "ç" * 200
    write_sources(ds_mixed, rows)
    df = load_manifest(ds_mixed, external_sources=reg(ds_mixed))
    assert len(df) == 121


def test_extra_contributor_line_for_external_item(ds_mixed: Path) -> None:
    rows = read_sources(ds_mixed)
    row = _first(rows, "external")
    row.update({"origin": "contributor", "contributor": "c02", "source_id": "", "source_ref": ""})
    write_sources(ds_mixed, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_mixed, external_sources=reg(ds_mixed))
    assert "external_item_mismatch" in codes(problems_of(excinfo))


def test_extra_excluded_line_skips_duplicate_input(ds_mixed: Path) -> None:
    """§4.2: excluded lines do not enter duplicate_input; source_unknown_image is not affected."""
    rows = read_sources(ds_mixed)
    contributors = [r for r in rows if r["origin"] == "contributor"]
    victim = contributors[1]["image_path"]
    contributors[1]["input_sha256"] = contributors[0]["input_sha256"]
    write_sources(ds_mixed, rows)
    (_inside(ds_mixed / victim, ds_mixed)).unlink()
    write_csv(ds_mixed / "exclusions.csv", ["image_path", "reason"], [[victim, "person"]])
    df = load_manifest(ds_mixed, external_sources=reg(ds_mixed))
    assert len(df) == 120


def test_extra_prefix_rules_for_external_items(ds_plain: Path) -> None:
    sources: list[dict[str, str]] = []
    write_registry(reg(ds_plain), [SYNTHETIC_SOURCE])
    for k, (item, otype, grade) in enumerate(
        [("XS-0001", "nut", "good"), ("XT-0001", "screw", "good"), ("XO-0001", "other", None)]
    ):
        rel = add_image(ds_plain, item, otype, grade, 0, f"20261107T10{k:02d}00Z")
        sources.append(
            {
                "image_path": rel,
                "origin": "external",
                "contributor": "",
                "source_id": "synthetic",
                "source_ref": f"s/{item}.png",
                "input_sha256": sha256_file(ds_plain / rel),
            }
        )
    write_sources(ds_plain, sources)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds_plain, external_sources=reg(ds_plain))
    problems = problems_of(excinfo)
    mismatched = {p.image_path for p in problems if p.code == "item_prefix_mismatch"}
    assert any("XS-0001" in (p or "") for p in mismatched), [str(p) for p in problems]
    assert not any("XO-0001" in (p or "") for p in mismatched)
    # XT- is not a valid item_id in the MVP (fails the pattern or the prefix check)
    xt = [p for p in problems if p.image_path and "XT-0001" in p.image_path]
    assert xt, [str(p) for p in problems]


def test_extra_make_split_invalid_ceiling(_t203_e1: Path, tmp_path: Path) -> None:
    ds = copy_template(_t203_e1, tmp_path)
    df = load_manifest(ds, external_sources=reg(ds))
    for bad in (0, 0.0, -0.1, 1.0000001, 1.5):
        with pytest.raises(ValueError):
            make_split(df, seed=42, max_external_fraction=bad)
    result = make_split(df, seed=42, max_external_fraction=1)
    assert len(result.frame) == len(df)


def test_extra_make_split_ceiling_is_exact(tmp_path: Path) -> None:
    ds = _gen_ext(tmp_path, 18)  # 198/660 in train: exactly 0.30
    df = load_manifest(ds, external_sources=reg(ds))
    make_split(df, seed=42, max_external_fraction=0.3)
    with pytest.raises(SplitError, match=r"external fraction in train 198/660 above 0\.29"):
        make_split(df, seed=42, max_external_fraction=0.29)


def test_extra_history_with_external_out_of_train(_t203_e1: Path, tmp_path: Path) -> None:
    ds = copy_template(_t203_e1, tmp_path)
    df = load_manifest(ds, external_sources=reg(ds))
    v1 = make_split(df, seed=42).frame
    with pytest.raises(SplitIntegrityError, match="XN-0003"):
        make_split(df, seed=42, previous=v1, history={"XN-0003": "val"})
    edited = v1.copy()
    victim = df.loc[df["item_id"] == "XO-0001", "image_path"].iloc[0]
    edited.loc[edited["image_path"] == victim, "split"] = "val"
    with pytest.raises(SplitIntegrityError, match="XO-0001"):
        item_history([edited], df)


def test_extra_split_json_without_externals(ds_plain: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    rc, out = split_cli(ds_plain, splits, capsys, registry=tmp_path / "absent.csv")
    assert rc == 0, out
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["max_external_fraction"] == 0.3
    assert meta["external_fraction_train"] == 0
    assert n_external_images(meta) == {"train": 0, "val": 0, "test": 0}


@pytest.mark.parametrize("value", ["nan", "inf", "-0.1", "", "0.0", "1.0000001"])
def test_extra_split_cli_more_invalid_ceilings(ds_plain: Path, tmp_path: Path, capsys, value):
    splits = tmp_path / "splits"
    rc, out = split_cli(ds_plain, splits, capsys, "--max-external-fraction", value)
    assert rc == 2, (value, out)
    assert tree_snapshot(splits) == {}


def test_extra_split_cli_ceiling_one(ds_plain: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    rc, out = split_cli(ds_plain, splits, capsys, "--max-external-fraction", "1")
    assert rc == 0, out
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["max_external_fraction"] == 1


def test_extra_external_never_counted_as_missing_from_old_split(
    _t203_e1: Path, tmp_path: Path, capsys
) -> None:
    """An external image whose sources.csv line is missing still goes to train (§7: the rule
    depends only on the item_id); validate reports missing_source."""
    ds = copy_template(_t203_e1, tmp_path)
    df = load_manifest(ds, external_sources=reg(ds))
    df = df.drop(columns=["origin", "contributor", "source_id"])
    frame = make_split(df, seed=42).frame
    mapping = dict(zip(frame["image_path"], frame["split"], strict=True))
    ext = df.loc[df["item_id"].map(is_external_item), "image_path"]
    assert all(mapping[p] == "train" for p in ext)


def test_extra_data_report_without_split(ds_mixed: Path) -> None:
    df = load_manifest(ds_mixed, external_sources=reg(ds_mixed))
    report = build_data_report(df, None)
    assert set(report["counts_by_origin"]) == set(ORIGINS)
    for origin in ORIGINS:
        assert report["counts_by_origin"][origin]["by_split"] == {}
    assert report["external_fraction_train"] is None
    assert report["by_source"] == {"synthetic": 11}
    assert report["n_contributors"] == 1


def test_extra_data_report_unchanged_without_externals(ds_plain: Path, tmp_path: Path) -> None:
    df = load_manifest(ds_plain, external_sources=tmp_path / "absent.csv")
    report = build_data_report(df, None)
    assert report["by_source"] == {}
    assert report["n_contributors"] == 0
    assert report["counts_by_origin"]["capture"]["n_images"] == 88
    assert report["counts_by_origin"]["external"]["n_images"] == 0
    assert report["items_per_grade"]["screw"]["fair"] == 4


def test_extra_release_notes_exact_text(model_env: SimpleNamespace) -> None:
    notes = model_env.root / "notes.md"
    proc = release_notes(model_env, output=notes)
    assert proc.returncode == 0, proc.stderr
    sha = (model_env.model_dir / "model.sha256").read_text(encoding="utf-8").rstrip("\n")
    expected = f"sha256: {sha}\n\n{NOTES_TITLE}\n\n{SYNTH_NOTES_LINE}\n\n{PATHS_LINE}\n"
    assert notes.read_text(encoding="utf-8") == expected


def test_extra_release_notes_stdout_bytes_with_c_locale(model_env: SimpleNamespace) -> None:
    notes = model_env.root / "notes.md"
    assert release_notes(model_env, output=notes).returncode == 0
    env = {k: v for k, v in _env().items() if k != "PYTHONIOENCODING"}
    env.update({"LC_ALL": "C", "LANG": "C"})
    args = ["release-notes", "--model-dir", str(model_env.model_dir)]
    args += ["--external-sources", str(model_env.registry)]
    proc = subprocess.run(
        [sys.executable, "-m", "qc_ml.report", *args],
        cwd=model_env.root,
        capture_output=True,
        env=env,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == notes.read_bytes()


def test_extra_release_notes_overwrites_existing_output(model_env: SimpleNamespace) -> None:
    notes = model_env.root / "notes.md"
    notes.write_text("antigo\n", encoding="utf-8")
    proc = release_notes(model_env, output=notes)
    assert proc.returncode == 0, proc.stderr
    assert notes.read_text(encoding="utf-8").startswith("sha256: ")
    assert [p.name for p in model_env.root.iterdir() if p.name.startswith("notes")] == ["notes.md"]


def test_extra_release_notes_without_registry_file(model_env: SimpleNamespace) -> None:
    """Registry absent = empty registry: a model with external images cannot get notes."""
    notes = model_env.root / "notes.md"
    proc = release_notes(model_env, output=notes, registry=model_env.root / "absent.csv")
    assert proc.returncode == 2
    assert "source not in registry: synthetic" in proc.stderr
    assert not notes.exists()


def test_extra_release_notes_invalid_ids_sorted_and_not_echoed(model_env: SimpleNamespace) -> None:
    metrics = load_metrics(model_env)
    metrics["counts"]["train"]["by_source"] = {
        "zz-b": 1,
        "synthetic": 11,
        "yy-a": 1,
        "X\nsource not in registry: forged": 1,
    }
    save_metrics(model_env, metrics)
    err = _notes_fail(model_env, model_env.root / "notes.md")
    lines = [ln for ln in err.splitlines() if ln.startswith("source not in registry:")]
    assert "source not in registry: forged" not in lines
    assert "source not in registry: yy-a" in lines and "source not in registry: zz-b" in lines
    assert lines.index("source not in registry: yy-a") < lines.index("source not in registry: zz-b")


def test_extra_changelog_fraction_rounds_up(model_env: SimpleNamespace) -> None:
    metrics = load_metrics(model_env)
    train = metrics["counts"]["train"]
    n_train = sum(train["by_origin"].values())
    assert n_train == 55
    # 11/55 exact; edit to 1 external of 3 images to check ROUND_CEILING (0,3334)
    train["by_origin"] = {"capture": 2, "contributor": 0, "external": 1}
    train["by_source"] = {"synthetic": 1}
    for key in ("n_images", "images"):
        if key in train:
            train[key] = 3
    save_metrics(model_env, metrics)
    cl = changelog(model_env)
    assert cl.returncode == 0, cl.stderr
    data = data_section(cl.stdout)
    treino = [ln for ln in data if ln.startswith("- Treino:")]
    assert treino == ["- Treino: 1 imagens externas de 3 (0,3334)."], (treino, train)
    assert Fraction(1, 3) <= Fraction(3334, 10000)


def test_extra_config_external_sources_field(tmp_path: Path) -> None:
    from qc_ml.train import TrainConfig, load_config

    base = {
        "model_version": "partqc-cfg035-v1",
        "dataset_dir": str(tmp_path / "ds"),
        "split_file": str(tmp_path / "splits" / "split_v1.csv"),
    }
    path = tmp_path / "a.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    assert load_config(path).external_sources is None
    path.write_text(json.dumps({**base, "external_sources": "x/reg.csv"}), encoding="utf-8")
    assert load_config(path).external_sources == "x/reg.csv"
    assert "external_sources" in TrainConfig.__dataclass_fields__


def test_extra_split_counts_by_origin_direct(ds_mixed: Path) -> None:
    df = load_manifest(ds_mixed, external_sources=reg(ds_mixed))
    from qc_ml.predict import ModelLabels  # noqa: PLC0415 - public type used by split_counts

    labels = ModelLabels(object_types=("screw", "nut", "other"), grades=tuple(GRADES))
    counts = evaluate_mod.split_counts(df, labels)
    assert counts["by_origin"] == {"capture": 88, "contributor": 22, "external": 11}
    assert counts["by_source"] == {"synthetic": 11}
    plain = pd.DataFrame(df.drop(columns=["origin", "contributor", "source_id"]))
    assert isinstance(evaluate_mod.split_counts(plain, labels), dict)


def test_extra_generator_layout_of_contributor_and_external_items(tmp_path: Path) -> None:
    """§4.7: numbering, one image per external item, sources.csv rows and the registry."""
    root = make_synthetic_dataset(
        _inside(tmp_path / "ds", tmp_path),
        contributor_items_per_stratum=2,
        external_items_per_stratum=2,
    )
    rows = read_rows(root)
    items = {r["item_id"] for r in rows}
    assert {f"S-{n}" for n in range(501, 511)} <= items
    assert {f"N-{n}" for n in range(501, 511)} <= items
    assert {"O-501", "O-502"} <= items and "O-503" not in items
    assert {f"XS-{n:04d}" for n in range(1, 11)} <= items and "XS-0011" not in items
    assert {"XO-0001", "XO-0002"} <= items and "XO-0003" not in items
    ext_rows = [r for r in rows if is_external_item(r["item_id"])]
    assert len(ext_rows) == 22
    assert all(r["angle"] == "0" for r in ext_rows)
    sources = {r["image_path"]: r for r in read_sources(root)}
    assert len(sources) == 22 + 22 * 2
    with (root / "sources.csv").open("rb") as fh:
        assert fh.readline() == (",".join(SOURCES_HEADER) + "\n").encode()
    for row in rows:
        src = sources.get(row["image_path"])
        if is_external_item(row["item_id"]):
            assert src is not None
            assert (src["origin"], src["contributor"], src["source_id"]) == (
                "external",
                "",
                "synthetic",
            )
            assert src["source_ref"] == f"synthetic/{row['item_id']}.png"
        elif int(row["item_id"][2:]) >= 501:
            assert src is not None
            assert (src["origin"], src["contributor"], src["source_id"], src["source_ref"]) == (
                "contributor",
                "c01",
                "",
                "",
            )
        else:
            assert src is None
            continue
        assert src["input_sha256"] == sha256_file(root / row["image_path"])
    registry = load_external_sources(reg(root))
    assert list(registry) == ["synthetic"]
    synthetic = registry["synthetic"]
    for key in ("url", "license", "license_url", "attribution"):
        assert getattr(synthetic, key) == SYNTHETIC_SOURCE[key], key
    assert str(synthetic.retrieved_at) == "2026-10-20"


def test_extra_external_sources_is_not_a_hyperparameter(tmp_path: Path) -> None:
    from qc_ml.config import TrainConfig

    config = TrainConfig(
        model_version="partqc-cfg035-v1",
        dataset_dir=str(tmp_path / "ds"),
        split_file=str(tmp_path / "split_v1.csv"),
        external_sources=str(tmp_path / "reg.csv"),
    )
    deviations = config.deviations_from_defaults
    assert not any("external_sources" in json.dumps(d) for d in deviations), deviations
