"""Acceptance tests for SPEC-016 (qc-ml: hand tools, grade criterion, test extension, ADR-022).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-13 to CA-20, CA-22 and CA-23 (CA-21 is manual: real training with
photos of the tools, recorded as pending in the test report). Tests named ``test_extra_*`` are
exploratory edge cases around SPEC-016 sections 4.6 to 4.10 that no CA spells out.

Rules followed (``docs/architecture.md`` §10, R-11, R-14): every dataset is synthetic
(``make_synthetic_dataset`` plus images drawn here with Pillow) and lives under a temporary
directory; nothing under ``ml/data/`` is read; the split CLI runs as ``python -m qc_ml.split`` in
a subprocess (never pytest); the evaluation uses the ONNX fixture ``tiny_model_tools`` (no
torch); the only test that needs torch is skipped without it.

"Tools added" (CA-15, CA-20, CA-23): the split versions are written in one ``splits`` directory;
the first split reads the dataset generated without tools, the next ones read the dataset
generated with the same parameters plus the tools (the generator keeps every row of the dataset
without tools, which each fixture checks before using it).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from PIL import Image

from qc_ml import data as data_mod
from qc_ml import evaluate as evaluate_mod
from qc_ml import thresholds as thresholds_mod
from qc_ml.data import (
    DEFAULT_LABELS,
    KNOWN_OBJECT_TYPES,
    TOOL_GRADE_MIN_IMAGES,
    TOOL_GRADE_MIN_ITEMS,
    TOOL_OBJECT_TYPES,
    ModelLabels,
    build_data_report,
    derive_model_labels,
    grade_target,
    load_manifest,
)
from qc_ml.errors import ManifestError
from qc_ml.predict import Predictions
from qc_ml.split import load_split, rows_for
from qc_ml.synthetic import make_synthetic_dataset
from qc_ml.thresholds import choose_thresholds

pytestmark = pytest.mark.acceptance

REPO_ROOT = Path(__file__).resolve().parents[3]
ML_ROOT = REPO_ROOT / "ml"
TINY_TOOLS = ML_ROOT / "tests" / "fixtures" / "tiny_model_tools"
TINY_VERSION = "partqc-tiny016-v1"
TOOLS = ("pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver")
GRADES = ("perfect", "good", "fair", "poor", "unusable")
SPLITS = ("train", "val", "test")
TYPE_GRID = [round(0.50 + 0.01 * i, 2) for i in range(36)]  # SPEC-012 §4.6: 0.50 .. 0.85
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
ACC_SOURCE = [
    "acc016-fonte",
    "Fonte de teste 016",
    "https://example.org/acc016",
    "CC0-1.0",
    "https://creativecommons.org/publicdomain/zero/1.0/",
    "Synthetic test images",
    "2026-10-20",
]
METRIC_KEYS_012 = {
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
TOOL_METRIC_KEYS = {
    "grade_qwk",
    "grade_mae",
    "grade_off_by_one_accuracy",
    "n_images_test",
    "n_items_test",
}


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


def _inside(path: Path, root: Path) -> Path:
    resolved = Path(path).resolve()
    assert resolved.is_relative_to(Path(root).resolve()), f"{resolved} is outside {root}"
    return resolved


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv_rows(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def manifest_rows(root: Path) -> list[dict[str, str]]:
    return read_csv_rows(root / "manifest.csv")


def item_of(image_path: str) -> str:
    return Path(image_path).name.split("__")[0]


def type_of(image_path: str) -> str:
    return image_path.split("/")[1]


def grade_of(image_path: str) -> str:
    return image_path.split("/")[2]


def drop_rows(root: Path, keep) -> int:  # noqa: ANN001 - predicate over a manifest row
    """Remove from ``root`` the manifest rows where ``keep(row)`` is false (files and sources)."""
    rows = manifest_rows(root)
    kept = [r for r in rows if keep(r)]
    removed = {r["image_path"] for r in rows if not keep(r)}
    for rel in removed:
        _inside(root / rel, root).unlink()
    write_csv_rows(root / "manifest.csv", MANIFEST_HEADER, kept)
    sources = root / "sources.csv"
    if sources.exists():
        src_rows = [r for r in read_csv_rows(sources) if r["image_path"] not in removed]
        write_csv_rows(sources, SOURCES_HEADER, src_rows)
    return len(removed)


def write_jpeg(path: Path, seed: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(seed.encode()).digest()
    img = Image.new("RGB", (64, 64), (200 + digest[0] % 50, 200 + digest[1] % 50, 210))
    for x in range(20, 44):
        for y in range(8, 56):
            img.putpixel((x, y), (90 + digest[2] % 60, 90, 100))
    img.save(path, format="JPEG", quality=90)


def add_image(root: Path, item_id: str, object_type: str, grade: str, angle: int, ts: str) -> str:
    """One image (file + manifest row) in the SPEC-010 layout; ``ts`` like 20261201T100000Z."""
    rel = f"raw/{object_type}/{grade or '_'}/{item_id}__{angle}__{ts}.jpg"
    write_jpeg(root / rel, rel)
    rows = manifest_rows(root)
    rows.append(
        {
            "image_path": rel,
            "item_id": item_id,
            "object_type": object_type,
            "grade": grade,
            "labeler": "a",
            "angle": str(angle),
            "captured_at": f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[9:11]}:{ts[11:13]}:{ts[13:15]}Z",
            "capture_device": "synthetic",
            "notes": "",
        }
    )
    write_csv_rows(root / "manifest.csv", MANIFEST_HEADER, rows)
    return rel


def add_external(root: Path, item_id: str, object_type: str, grade: str, n: int) -> str:
    """One external image with its ``sources.csv`` line and the test source in the registry."""
    ts = f"20261202T10{n // 60:02d}{n % 60:02d}Z"
    rel = add_image(root, item_id, object_type, grade, 0, ts)
    sources = root / "sources.csv"
    rows = read_csv_rows(sources) if sources.exists() else []
    rows.append(
        {
            "image_path": rel,
            "origin": "external",
            "contributor": "",
            "source_id": ACC_SOURCE[0],
            "source_ref": f"acc016/{item_id}.png",
            "input_sha256": hashlib.sha256(f"acc016-{item_id}".encode()).hexdigest(),
        }
    )
    write_csv_rows(sources, SOURCES_HEADER, rows)
    registry = root / "external_sources.csv"
    lines = registry.read_text(encoding="utf-8").splitlines() if registry.exists() else []
    if not lines:
        lines = [",".join(REGISTRY_HEADER)]
    if not any(line.startswith(ACC_SOURCE[0] + ",") for line in lines):
        lines.append(",".join(ACC_SOURCE))
    registry.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rel


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["HF_HUB_OFFLINE"] = "1"
    return env


def run_module(module: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        env=_env(),
        check=False,
    )


def split_cli(dataset: Path, splits: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    args = [
        "--dataset-dir",
        str(dataset),
        "--splits-dir",
        str(splits),
        "--seed",
        "42",
        "--external-sources",
        str(dataset / "external_sources.csv"),
        *extra,
    ]
    return run_module("qc_ml.split", args, cwd=splits.parent)


def read_split(path: Path) -> dict[str, str]:
    return {r["image_path"]: r["split"] for r in read_csv_rows(path)}


def split_json(path: Path) -> dict[str, Any]:
    return json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))


def items_by_split(split_map: dict[str, str], object_type: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {w: set() for w in SPLITS}
    for path, which in split_map.items():
        if type_of(path) == object_type:
            out[which].add(item_of(path))
    return out


def snapshot(path: Path) -> dict[str, bytes]:
    if not path.exists():
        return {}
    return {
        p.relative_to(path).as_posix(): p.read_bytes()
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def copy_dataset(template: Path, dest: Path) -> Path:
    return Path(shutil.copytree(template, dest))


def assert_tools_dataset_extends(base: Path, tools: Path) -> None:
    """Precondition of "tools added": every base row is in the tools dataset, same bytes."""
    base_rows = {tuple(r.values()) for r in manifest_rows(base)}
    tool_rows = {tuple(r.values()) for r in manifest_rows(tools)}
    assert base_rows <= tool_rows
    extra = tool_rows - base_rows
    assert extra and all(r[1].startswith(("T-", "XT-")) for r in extra)
    for r in manifest_rows(base)[:20]:
        assert (base / r["image_path"]).read_bytes() == (tools / r["image_path"]).read_bytes()


def gen(factory: pytest.TempPathFactory, name: str, **kwargs: Any) -> Path:
    return make_synthetic_dataset(factory.mktemp(name) / "ds", **kwargs)


# --------------------------------------------------------------------------------------------
# Templates (generated once per module)
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def t_default(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(tmp_path_factory, "s016_default")


@pytest.fixture(scope="module")
def t_tools1(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(tmp_path_factory, "s016_tools1", tool_items_per_stratum=1)


@pytest.fixture(scope="module")
def t_base12(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(tmp_path_factory, "s016_base12", images_per_item=12)


@pytest.fixture(scope="module")
def t_tools12(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(tmp_path_factory, "s016_tools12", images_per_item=12, tool_items_per_stratum=5)


@pytest.fixture(scope="module")
def t_base203(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(tmp_path_factory, "s016_base203", items_per_stratum=20, images_per_item=3)


@pytest.fixture(scope="module")
def t_tools203(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(
        tmp_path_factory,
        "s016_tools203",
        items_per_stratum=20,
        images_per_item=3,
        tool_items_per_stratum=4,
    )


@pytest.fixture(scope="module")
def t_tools203_ext(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(
        tmp_path_factory,
        "s016_tools203_ext",
        items_per_stratum=20,
        images_per_item=3,
        tool_items_per_stratum=4,
        external_tool_items_per_type=2,
    )


# --------------------------------------------------------------------------------------------
# CA-15 state: split_v1 -> (a) -> (b) defer -> (c) extend -> (d) one new pliers item
# --------------------------------------------------------------------------------------------


def _run_ca15_chain(root: Path, base_template: Path, tools_template: Path) -> SimpleNamespace:
    base = copy_dataset(base_template, root / "base")
    tools = copy_dataset(tools_template, root / "tools")
    assert_tools_dataset_extends(base, tools)
    splits = root / "splits"
    v1 = split_cli(base, splits)
    assert v1.returncode == 0, v1.stdout + v1.stderr
    after_v1 = snapshot(splits)

    a = split_cli(tools, splits)
    after_a = snapshot(splits)

    tools_csv = ",".join(TOOLS)
    b = split_cli(tools, splits, "--defer-types", tools_csv)
    after_b = snapshot(splits)
    c = split_cli(tools, splits, "--extend-test-types", tools_csv)
    after_c = snapshot(splits)
    return SimpleNamespace(
        root=root,
        base=base,
        tools=tools,
        splits=splits,
        after_v1=after_v1,
        a=a,
        after_a=after_a,
        b=b,
        after_b=after_b,
        c=c,
        after_c=after_c,
    )


@pytest.fixture(scope="module")
def ca15(
    tmp_path_factory: pytest.TempPathFactory, t_base203: Path, t_tools203: Path
) -> SimpleNamespace:
    state = _run_ca15_chain(tmp_path_factory.mktemp("s016_ca15"), t_base203, t_tools203)
    # (d): one new pliers item after the extension.
    new_paths = [
        add_image(state.tools, "T-101", "pliers", "fair", angle, f"20261203T1000{angle:02d}Z")
        for angle in range(3)
    ]
    state.d_new_paths = new_paths
    state.d = split_cli(state.tools, state.splits)
    state.after_d = snapshot(state.splits)
    return state


@pytest.fixture(scope="module")
def ca20(
    tmp_path_factory: pytest.TempPathFactory, t_base203: Path, t_tools203_ext: Path
) -> SimpleNamespace:
    return _run_ca15_chain(tmp_path_factory.mktemp("s016_ca20"), t_base203, t_tools203_ext)


# --------------------------------------------------------------------------------------------
# CA-13
# --------------------------------------------------------------------------------------------


def test_ca13_tools_load_with_25_t_items(t_tools1: Path, tmp_path: Path) -> None:
    root = copy_dataset(t_tools1, tmp_path / "ds")
    df = load_manifest(root, external_sources=root / "external_sources.csv")
    t_items = {i for i in df["item_id"] if str(i).startswith("T-")}
    assert len(t_items) == 25
    pairs = {(r.object_type, r.grade) for r in df.itertuples() if str(r.item_id).startswith("T-")}
    assert pairs == {(t, g) for t in TOOLS for g in GRADES}


def _problem_codes(excinfo: pytest.ExceptionInfo[ManifestError]) -> list[str]:
    return [p.code for p in excinfo.value.problems]


def test_ca13_t_item_edited_to_screw_is_a_prefix_mismatch(t_tools1: Path, tmp_path: Path) -> None:
    root = copy_dataset(t_tools1, tmp_path / "ds")
    rows = manifest_rows(root)
    (idx,) = [i for i, r in enumerate(rows) if r["item_id"] == "T-001"][:1]
    rows[idx]["object_type"] = "screw"
    write_csv_rows(root / "manifest.csv", MANIFEST_HEADER, rows)
    with pytest.raises(ManifestError) as info:
        load_manifest(root, external_sources=root / "external_sources.csv")
    assert "item_prefix_mismatch" in _problem_codes(info)


def test_ca13_tool_row_without_grade_is_missing_grade(t_tools1: Path, tmp_path: Path) -> None:
    root = copy_dataset(t_tools1, tmp_path / "ds")
    rows = manifest_rows(root)
    idx = next(i for i, r in enumerate(rows) if r["object_type"] == "allen_key")
    rows[idx]["grade"] = ""
    write_csv_rows(root / "manifest.csv", MANIFEST_HEADER, rows)
    with pytest.raises(ManifestError) as info:
        load_manifest(root, external_sources=root / "external_sources.csv")
    assert "missing_grade" in _problem_codes(info)


# --------------------------------------------------------------------------------------------
# CA-14
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ca14_report(t_tools12: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = copy_dataset(t_tools12, tmp_path_factory.mktemp("s016_ca14") / "ds")
    # Keep only pliers and allen_key among the own tool images.
    drop_rows(
        root,
        lambda r: r["object_type"] not in TOOLS or r["object_type"] in ("pliers", "allen_key"),
    )
    # allen_key: one image less in one grade (59 in "poor").
    victim = next(
        r for r in manifest_rows(root) if r["object_type"] == "allen_key" and r["grade"] == "poor"
    )
    drop_rows(root, lambda r: r["image_path"] != victim["image_path"])
    # 30 external images of flat_screwdriver (only external: no own image of that tool).
    for n in range(30):
        add_external(root, f"XT-{n + 1:04d}", "flat_screwdriver", GRADES[n % 5], n)
    out = root.parent / "data_report.json"
    proc = run_module(
        "qc_ml.data",
        [
            "report",
            "--dataset-dir",
            str(root),
            "--external-sources",
            str(root / "external_sources.csv"),
            "--out",
            str(out),
        ],
        cwd=root.parent,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_ca14_tool_grade_criterion(ca14_report: dict[str, Any]) -> None:
    cov = ca14_report["tool_grade_coverage"]
    assert cov["pliers"]["graded"] is True
    assert cov["allen_key"]["graded"] is False
    flat = cov["flat_screwdriver"]["by_grade"]
    assert all(cell == {"n_images": 0, "n_items": 0} for cell in flat.values()), flat
    assert set(cov) == set(TOOLS)
    for tool in TOOLS:
        assert set(cov[tool]["by_grade"]) == set(GRADES), tool
        for cell in cov[tool]["by_grade"].values():
            assert set(cell) == {"n_images", "n_items"}
    assert cov["pliers"]["by_grade"]["good"] == {"n_images": 60, "n_items": 5}
    assert cov["allen_key"]["by_grade"]["poor"] == {"n_images": 59, "n_items": 5}
    assert cov["flat_screwdriver"]["graded"] is False


def test_extra_criterion_constants() -> None:
    assert TOOL_GRADE_MIN_IMAGES == 60
    assert TOOL_GRADE_MIN_ITEMS == 5
    assert TOOL_OBJECT_TYPES == TOOLS
    assert ("screw", "nut", "other", *TOOLS) == KNOWN_OBJECT_TYPES


def test_extra_criterion_needs_5_items_and_ignores_excluded(
    t_tools12: Path, tmp_path: Path
) -> None:
    """60 images from 4 items is not enough; an excluded image does not count."""
    root = copy_dataset(t_tools12, tmp_path / "ds")
    # pliers / perfect: 5 items x 12 images. Drop one whole item, then add 12 images to another
    # item of the same stratum: still 60 images, only 4 items.
    pliers_perfect = sorted(
        {
            r["item_id"]
            for r in manifest_rows(root)
            if r["object_type"] == "pliers" and r["grade"] == "perfect"
        }
    )
    assert len(pliers_perfect) == 5
    gone, keep = pliers_perfect[0], pliers_perfect[1]
    drop_rows(root, lambda r: r["item_id"] != gone)
    for k in range(12):
        add_image(root, keep, "pliers", "perfect", k % 5, f"20261204T1001{k:02d}Z")
    # adjustable_wrench / fair: exclude one image (deleted + exclusions.csv): 59 left.
    victim = next(
        r["image_path"]
        for r in manifest_rows(root)
        if r["object_type"] == "adjustable_wrench" and r["grade"] == "fair"
    )
    (root / victim).unlink()
    (root / "exclusions.csv").write_text(f"image_path,reason\n{victim},other\n", encoding="utf-8")
    df = load_manifest(root, external_sources=root / "external_sources.csv")
    cov = build_data_report(df)["tool_grade_coverage"]
    assert cov["pliers"]["by_grade"]["perfect"] == {"n_images": 60, "n_items": 4}
    assert cov["pliers"]["graded"] is False
    assert cov["adjustable_wrench"]["by_grade"]["fair"] == {"n_images": 59, "n_items": 5}
    assert cov["adjustable_wrench"]["graded"] is False
    assert cov["phillips_screwdriver"]["graded"] is True


# --------------------------------------------------------------------------------------------
# CA-15
# --------------------------------------------------------------------------------------------


def test_ca15a_new_tools_need_a_decision(ca15: SimpleNamespace) -> None:
    assert ca15.a.returncode == 2, ca15.a.stdout + ca15.a.stderr
    lines = ca15.a.stderr.splitlines()
    for tool in TOOLS:
        assert lines.count(f"new object type without decision: {tool}") == 1, ca15.a.stderr
    assert ca15.after_a == ca15.after_v1  # nothing written


def test_ca15b_defer_the_tools(ca15: SimpleNamespace) -> None:
    assert ca15.b.returncode == 0, ca15.b.stdout + ca15.b.stderr
    v2 = read_split(ca15.splits / "split_v2.csv")
    assert not any(item_of(p).startswith("T-") for p in v2)
    meta = split_json(ca15.splits / "split_v2.csv")
    assert sorted(meta["deferred_types"]) == sorted(TOOLS)
    assert meta["test_extended_types"] == []


def test_ca15c_extend_the_test_with_the_tools(ca15: SimpleNamespace) -> None:
    assert ca15.c.returncode == 0, ca15.c.stdout + ca15.c.stderr
    v1 = read_split(ca15.splits / "split_v1.csv")
    v3 = read_split(ca15.splits / "split_v3.csv")
    for tool in TOOLS:
        by_split = items_by_split(v3, tool)
        assert all(by_split[w] for w in SPLITS), (tool, by_split)
        assert sum(len(s) for s in by_split.values()) == 20, tool
    for path, which in v1.items():
        assert v3[path] == which, path
    meta = split_json(ca15.splits / "split_v3.csv")
    assert sorted(meta["test_extended_types"]) == sorted(TOOLS)


def test_ca15d_new_item_of_an_extended_type_is_not_in_test(ca15: SimpleNamespace) -> None:
    assert ca15.d.returncode == 0, ca15.d.stdout + ca15.d.stderr
    latest = sorted(ca15.splits.glob("split_v*.csv"), key=lambda p: int(p.stem.split("_v")[1]))[-1]
    assert latest.name == "split_v4.csv"
    v4 = read_split(latest)
    for path in ca15.d_new_paths:
        assert v4[path] in ("train", "val"), (path, v4[path])
    v3 = read_split(ca15.splits / "split_v3.csv")
    for path, which in v3.items():
        assert v4[path] == which, path


def test_ca15e_too_few_items_to_extend(t_base203: Path, t_tools203: Path, tmp_path: Path) -> None:
    base = copy_dataset(t_base203, tmp_path / "base")
    tools = copy_dataset(t_tools203, tmp_path / "tools")
    splits = tmp_path / "splits"
    assert split_cli(base, splits).returncode == 0
    allen = sorted({r["item_id"] for r in manifest_rows(tools) if r["object_type"] == "allen_key"})
    keep = set(allen[:2])
    drop_rows(tools, lambda r: r["object_type"] != "allen_key" or r["item_id"] in keep)
    before = snapshot(splits)
    others = ",".join(t for t in TOOLS if t != "allen_key")
    proc = split_cli(tools, splits, "--extend-test-types", "allen_key", "--defer-types", others)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "too few items to extend the test: allen_key" in proc.stderr
    assert snapshot(splits) == before


# --------------------------------------------------------------------------------------------
# CA-23
# --------------------------------------------------------------------------------------------


def _extend_all(
    base_t: Path, tools_t: Path, root: Path
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    base = copy_dataset(base_t, root / "base")
    tools = copy_dataset(tools_t, root / "tools")
    assert_tools_dataset_extends(base, tools)
    splits = root / "splits"
    v1 = split_cli(base, splits)
    assert v1.returncode == 0, v1.stdout + v1.stderr
    proc = split_cli(tools, splits, "--extend-test-types", ",".join(TOOLS))
    return proc, splits, tools


@pytest.fixture(scope="module")
def ca23_ungraded(
    t_default: Path, t_tools1: Path, tmp_path_factory: pytest.TempPathFactory
) -> SimpleNamespace:
    root = tmp_path_factory.mktemp("s016_ca23a")
    proc, splits, tools = _extend_all(t_default, t_tools1, root)
    return SimpleNamespace(proc=proc, splits=splits, tools=tools, root=root)


def test_ca23_ungraded_tool_is_one_stratum(ca23_ungraded: SimpleNamespace) -> None:
    proc = ca23_ungraded.proc
    assert proc.returncode == 0, proc.stdout + proc.stderr
    v2 = read_split(ca23_ungraded.splits / "split_v2.csv")
    for tool in TOOLS:
        by_split = items_by_split(v2, tool)
        counts = {w: len(by_split[w]) for w in SPLITS}
        assert counts == {"train": 3, "val": 1, "test": 1}, (tool, counts)


def test_ca23_graded_tool_is_split_by_grade(
    t_base12: Path, t_tools12: Path, tmp_path: Path
) -> None:
    proc, splits, _ = _extend_all(t_base12, t_tools12, tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    v2 = read_split(splits / "split_v2.csv")
    for tool in TOOLS:
        per_grade: dict[str, dict[str, set[str]]] = defaultdict(lambda: {w: set() for w in SPLITS})
        for path, which in v2.items():
            if type_of(path) == tool:
                per_grade[grade_of(path)][which].add(item_of(path))
        assert set(per_grade) == set(GRADES), tool
        for grade in GRADES:
            counts = {w: len(per_grade[grade][w]) for w in SPLITS}
            assert counts == {"train": 3, "val": 1, "test": 1}, (tool, grade, counts)


# --------------------------------------------------------------------------------------------
# CA-16
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ca16_labels(t_tools12: Path, tmp_path_factory: pytest.TempPathFactory) -> ModelLabels:
    root = copy_dataset(t_tools12, tmp_path_factory.mktemp("s016_ca16") / "ds")
    victim = next(r["image_path"] for r in manifest_rows(root) if r["object_type"] == "allen_key")
    (root / victim).unlink()
    (root / "exclusions.csv").write_text(f"image_path,reason\n{victim},other\n", encoding="utf-8")
    df = load_manifest(root, external_sources=root / "external_sources.csv")
    assert victim not in set(df["image_path"])
    return derive_model_labels(df, df)


def test_ca16_model_labels_with_tools(ca16_labels: ModelLabels) -> None:
    assert tuple(ca16_labels.object_types) == (
        "screw",
        "nut",
        "other",
        "pliers",
        "adjustable_wrench",
        "allen_key",
        "flat_screwdriver",
        "phillips_screwdriver",
    )
    assert tuple(ca16_labels.ungraded_object_types) == ("allen_key",)


def test_ca16_model_labels_of_the_mvp(t_default: Path) -> None:
    df = load_manifest(t_default, external_sources=t_default / "external_sources.csv")
    labels = derive_model_labels(df, df)
    assert tuple(labels.object_types) == tuple(DEFAULT_LABELS.object_types)
    assert tuple(labels.grades) == tuple(DEFAULT_LABELS.grades)
    assert tuple(labels.ungraded_object_types) == ()


def test_ca16_grade_target(ca16_labels: ModelLabels) -> None:
    assert grade_target("allen_key", "good", ca16_labels) is None
    assert grade_target("other", None, ca16_labels) is None
    assert grade_target("pliers", "fair", ca16_labels) == 2


def test_extra_model_labels_follow_the_train_rows(t_tools12: Path) -> None:
    """``object_types`` come from ``train_rows``; the ungraded tools from the whole ``df``."""
    df = load_manifest(t_tools12, external_sources=t_tools12 / "external_sources.csv")
    train = df[~df["object_type"].isin(["adjustable_wrench", "phillips_screwdriver"])]
    labels = derive_model_labels(df, train)
    assert tuple(labels.object_types) == (
        "screw",
        "nut",
        "other",
        "pliers",
        "allen_key",
        "flat_screwdriver",
    )
    assert tuple(labels.ungraded_object_types) == ()
    assert grade_target("screw", "unusable", labels) == 4
    assert grade_target("nut", "perfect", labels) == 0


# --------------------------------------------------------------------------------------------
# CA-17 and CA-22
# --------------------------------------------------------------------------------------------

LABELS_4 = ModelLabels(object_types=("screw", "nut", "other", "pliers"), grades=GRADES)


def _preds(rows: list[tuple[str, list[float], list[float], int]]) -> Predictions:
    types = list(LABELS_4.object_types)
    return Predictions(
        split="val",
        image_paths=tuple(f"raw/x/{i:03d}.jpg" for i in range(len(rows))),
        type_probs=np.asarray([r[1] for r in rows], dtype=np.float64),
        grade_probs=np.asarray([r[2] for r in rows], dtype=np.float64),
        true_type_idx=np.asarray([types.index(r[0]) for r in rows]),
        true_grade_idx=np.asarray([r[3] for r in rows]),
    )


def _fu(rows: list[tuple[str, list[float], list[float], int]], t: float) -> Fraction:
    counted = [r for r in rows if r[0] != "other"]
    bad = [r for r in counted if max(r[1]) < t or int(np.argmax(r[1])) == 2]
    return Fraction(len(bad), len(counted))


def test_ca17_false_unknown_counts_the_tools() -> None:
    hi_grade = [0.9, 0.025, 0.025, 0.025, 0.025]
    rows = [("screw", [0.95, 0.02, 0.02, 0.01], hi_grade, 0) for _ in range(10)]
    rows += [("pliers", [0.15, 0.15, 0.15, 0.55], hi_grade, 0) for _ in range(2)]
    rows += [("pliers", [0.02, 0.02, 0.01, 0.95], hi_grade, 0) for _ in range(8)]
    result = choose_thresholds(_preds(rows), LABELS_4)
    expected = max(t for t in TYPE_GRID if _fu(rows, t) <= Fraction(5, 100))
    assert expected == 0.55
    assert result.decision.type_threshold == pytest.approx(expected)
    assert result.decision.type_threshold <= 0.55


def test_ca22_review_threshold_counts_screw_nut_and_other() -> None:
    low = [0.50, 0.20, 0.10, 0.10, 0.10]
    high = [0.95, 0.02, 0.01, 0.01, 0.01]
    rows = [("screw", [0.97, 0.01, 0.01, 0.01], low, 0) for _ in range(2)]
    rows += [("screw", [0.97, 0.01, 0.01, 0.01], high, 0) for _ in range(8)]
    rows += [("other", [0.01, 0.01, 0.97, 0.01], high, -1) for _ in range(10)]
    rows += [("pliers", [0.01, 0.01, 0.01, 0.97], low, 0) for _ in range(20)]
    result = choose_thresholds(_preds(rows), LABELS_4)
    assert result.decision.type_threshold == pytest.approx(0.85)
    assert result.decision.grade_review_threshold == pytest.approx(0.60)
    assert "review_adjusted" not in json.dumps(result.report["notes"])


def test_extra_review_threshold_adjusts_without_the_other_images() -> None:
    """Contrast case for CA-22: without the 10 ``other`` images the fraction is 2/10 = 20%,
    outside [5%, 15%], so the threshold must move (``review_adjusted``)."""
    low = [0.50, 0.20, 0.10, 0.10, 0.10]
    high = [0.95, 0.02, 0.01, 0.01, 0.01]
    rows = [("screw", [0.97, 0.01, 0.01, 0.01], low, 0) for _ in range(2)]
    rows += [("screw", [0.97, 0.01, 0.01, 0.01], high, 0) for _ in range(8)]
    rows += [("pliers", [0.01, 0.01, 0.01, 0.97], high, 0) for _ in range(20)]
    result = choose_thresholds(_preds(rows), LABELS_4)
    # 0% (r <= 0.50) and 20% (r > 0.50) tie at 10 points from the target; the tie goes to
    # the value nearest 0.60 (SPEC-012 section 4.6), so the value stays 0.60 but is adjusted.
    assert "review_adjusted" in json.dumps(result.report["notes"])


def test_extra_unusable_threshold_ignores_the_tools() -> None:
    """Section 4.8: the tool images do not enter ``unusable_threshold``."""
    rows = [("screw", [0.97, 0.01, 0.01, 0.01], [0.05, 0.05, 0.1, 0.1, 0.7], 4) for _ in range(10)]
    rows += [
        ("screw", [0.97, 0.01, 0.01, 0.01], [0.9, 0.025, 0.025, 0.025, 0.025], 0) for _ in range(10)
    ]
    reference = choose_thresholds(_preds(rows), LABELS_4).decision.unusable_threshold
    # 10 pliers truly unusable whose p_unusable is tiny: they would pull the threshold down.
    rows_tools = rows + [
        ("pliers", [0.01, 0.01, 0.01, 0.97], [0.6, 0.3, 0.05, 0.04, 0.01], 4) for _ in range(10)
    ]
    with_tools = choose_thresholds(_preds(rows_tools), LABELS_4).decision.unusable_threshold
    assert with_tools == pytest.approx(reference)


# --------------------------------------------------------------------------------------------
# CA-18
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ca18(
    ca23_ungraded: SimpleNamespace, tmp_path_factory: pytest.TempPathFactory
) -> SimpleNamespace:
    assert ca23_ungraded.proc.returncode == 0
    root = tmp_path_factory.mktemp("s016_ca18")
    dataset_dir = ca23_ungraded.tools
    split_file = ca23_ungraded.splits / "split_v2.csv"
    config = {
        "model_version": TINY_VERSION,
        "dataset_dir": str(dataset_dir),
        "split_file": str(split_file),
        "backbone": "tiny",
        "pretrained": False,
        "epochs_a": 1,
        "epochs_b_max": 1,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(root / "models"),
        "reports_root": str(root / "reports"),
        "checkpoints_root": str(root / "checkpoints"),
        "external_sources": str(dataset_dir / "external_sources.csv"),
    }
    config_path = root / "config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    model_dir = root / "models" / TINY_VERSION
    shutil.copytree(TINY_TOOLS, model_dir)
    rc_t = thresholds_mod.main(["--config", str(config_path)])
    rc_e = evaluate_mod.main(["--config", str(config_path)])
    metrics_path = model_dir / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    return SimpleNamespace(
        root=root,
        rc_t=rc_t,
        rc_e=rc_e,
        model_dir=model_dir,
        metrics=metrics,
        split_file=split_file,
        dataset_dir=dataset_dir,
    )


def test_ca18_evaluate_with_tools(ca18: SimpleNamespace) -> None:
    assert ca18.rc_t == 0
    assert ca18.rc_e == 0
    m = ca18.metrics
    assert set(m) == METRIC_KEYS_012 | {"tool_grade_metrics"}, set(m) ^ METRIC_KEYS_012
    assert np.asarray(m["type_confusion"]).shape == (8, 8)
    assert m["labels"]["ungraded_object_types"] == ["allen_key"]
    tgm = m["tool_grade_metrics"]
    assert "allen_key" not in tgm
    graded_tools = [t for t in m["labels"]["object_types"] if t in TOOLS and t not in ["allen_key"]]
    assert sorted(tgm) == sorted(graded_tools)
    for tool in graded_tools:
        assert set(tgm[tool]) == TOOL_METRIC_KEYS, tool


def test_ca18_fixture_labels_json_has_the_ungraded_types() -> None:
    labels = json.loads((TINY_TOOLS / "labels.json").read_text(encoding="utf-8"))
    assert labels["object_types"] == ["screw", "nut", "other", *TOOLS]
    assert labels["ungraded_object_types"] == ["allen_key"]
    assert labels["grades"] == list(GRADES)


def test_extra_type_confusion_counts_every_test_image(ca18: SimpleNamespace) -> None:
    n_test = sum(1 for w in read_split(ca18.split_file).values() if w == "test")
    assert int(np.asarray(ca18.metrics["type_confusion"]).sum()) == n_test


def test_extra_tool_metric_counts_and_values(ca18: SimpleNamespace) -> None:
    split = read_split(ca18.split_file)
    for tool, values in ca18.metrics["tool_grade_metrics"].items():
        test_paths = [p for p, w in split.items() if w == "test" and type_of(p) == tool]
        assert values["n_images_test"] == len(test_paths), tool
        assert values["n_items_test"] == len({item_of(p) for p in test_paths}), tool
        for key in ("grade_qwk", "grade_mae", "grade_off_by_one_accuracy"):
            v = values[key]
            assert v is None or isinstance(v, int | float), (tool, key, v)
        if values["grade_mae"] is not None:
            assert 0.0 <= values["grade_mae"] <= 4.0


def test_extra_few_test_items_warning_per_type(ca18: SimpleNamespace) -> None:
    split = read_split(ca18.split_file)
    warnings = ca18.metrics["warnings"]
    for t in ca18.metrics["labels"]["object_types"]:
        n_items = len({item_of(p) for p, w in split.items() if w == "test" and type_of(p) == t})
        line = f"few test items for {t}: {n_items}"
        assert (line in warnings) is (n_items < 2), (t, n_items, warnings)


def test_extra_grade_metrics_still_only_screw_and_nut(ca18: SimpleNamespace) -> None:
    """ADR-022, decision 6: ``grade_*`` measured only on screw/nut test images."""
    split = read_split(ca18.split_file)
    n = sum(1 for p, w in split.items() if w == "test" and type_of(p) in ("screw", "nut"))
    assert int(np.asarray(ca18.metrics["grade_confusion"]).sum()) == n


def test_extra_changelog_lists_the_model_types(ca18: SimpleNamespace) -> None:
    proc = run_module(
        "qc_ml.report", ["changelog", "--model-dir", str(ca18.model_dir)], cwd=ca18.root
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = proc.stdout.splitlines()
    types_line = (
        "- Tipos do modelo: screw, nut, other, pliers, adjustable_wrench, allen_key, "
        "flat_screwdriver, phillips_screwdriver; sem grau: allen_key."
    )
    assert types_line in lines, proc.stdout
    table_start = next(i for i, line in enumerate(lines) if line.startswith("|"))
    assert lines.index(types_line) < table_start
    assert "type_accuracy" in proc.stdout.split(types_line, 1)[1].split("|", 1)[0], proc.stdout


def test_extra_thresholds_report_and_decision_files(ca18: SimpleNamespace) -> None:
    decision = json.loads((ca18.model_dir / "decision.json").read_text(encoding="utf-8"))
    assert set(decision) == {"type_threshold", "unusable_threshold", "grade_review_threshold"}
    assert 0.50 <= decision["type_threshold"] <= 0.85


def test_extra_export_with_tools_writes_ungraded_types(tmp_path: Path) -> None:
    """The fixture script (export path) writes ``ungraded_object_types`` (needs torch)."""
    pytest.importorskip("torch")
    out = tmp_path / "tiny_tools"
    proc = subprocess.run(
        [
            sys.executable,
            str(ML_ROOT / "scripts" / "make_tiny_fixture.py"),
            "--with-tools",
            "--out",
            str(out),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=600,
        env=_env(),
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    labels = json.loads((out / "labels.json").read_text(encoding="utf-8"))
    assert labels["ungraded_object_types"] == ["allen_key"]
    assert len(labels["object_types"]) == 8


# --------------------------------------------------------------------------------------------
# CA-19
# --------------------------------------------------------------------------------------------


def test_ca19_defaults_are_byte_for_byte_the_same(t_default: Path, tmp_path: Path) -> None:
    explicit = make_synthetic_dataset(
        tmp_path / "explicit", tool_items_per_stratum=0, external_tool_items_per_type=0
    )
    a, b = snapshot(t_default), snapshot(explicit)
    assert a == b
    items = {r["item_id"] for r in manifest_rows(explicit)}
    assert not any(i.startswith(("T-", "XT-")) for i in items)


def test_extra_generator_numbering_of_tools(t_tools203_ext: Path) -> None:
    rows = manifest_rows(t_tools203_ext)
    t_items = sorted({r["item_id"] for r in rows if r["item_id"].startswith("T-")})
    assert t_items == [f"T-{n:03d}" for n in range(1, 101)]
    xt = sorted({r["item_id"] for r in rows if r["item_id"].startswith("XT-")})
    assert xt == [f"XT-{n:04d}" for n in range(1, 11)]
    per_item = defaultdict(int)
    for r in rows:
        per_item[r["item_id"]] += 1
    assert all(per_item[i] == 3 for i in t_items)
    assert all(per_item[i] == 1 for i in xt)
    sources = {r["image_path"]: r for r in read_csv_rows(t_tools203_ext / "sources.csv")}
    for r in rows:
        if r["item_id"].startswith("XT-"):
            assert sources[r["image_path"]]["origin"] == "external"
            assert sources[r["image_path"]]["source_id"] == "synthetic"
        if r["item_id"].startswith("T-"):
            assert r["image_path"] not in sources  # capture origin
    xt_types = defaultdict(set)
    for r in rows:
        if r["item_id"].startswith("XT-"):
            xt_types[r["object_type"]].add(r["item_id"])
    assert {t: len(v) for t, v in xt_types.items()} == dict.fromkeys(TOOLS, 2)


# --------------------------------------------------------------------------------------------
# CA-20
# --------------------------------------------------------------------------------------------


def test_ca20_no_item_in_two_splits_and_no_xt_in_val_or_test(ca20: SimpleNamespace) -> None:
    assert ca20.b.returncode == 0, ca20.b.stdout + ca20.b.stderr
    assert ca20.c.returncode == 0, ca20.c.stdout + ca20.c.stderr
    v3 = read_split(ca20.splits / "split_v3.csv")
    items: dict[str, set[str]] = {w: set() for w in SPLITS}
    for path, which in v3.items():
        items[which].add(item_of(path))
    assert items["train"].isdisjoint(items["val"])
    assert items["train"].isdisjoint(items["test"])
    assert items["val"].isdisjoint(items["test"])
    xt = [p for p in v3 if item_of(p).startswith("XT-")]
    assert len(xt) == 10
    assert all(v3[p] == "train" for p in xt)


# --------------------------------------------------------------------------------------------
# Extras: CLI decisions, deferred types in the readers
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def v1_with_tools(
    t_default: Path, t_tools1: Path, tmp_path_factory: pytest.TempPathFactory
) -> SimpleNamespace:
    root = tmp_path_factory.mktemp("s016_cli")
    base = copy_dataset(t_default, root / "base")
    tools = copy_dataset(t_tools1, root / "tools")
    splits = root / "splits"
    assert split_cli(base, splits).returncode == 0
    return SimpleNamespace(root=root, base=base, tools=tools, splits=splits)


@pytest.mark.parametrize(
    ("extra", "needle"),
    [
        (("--extend-test-types", "hammer"), None),
        (("--defer-types", "unknown"), None),
        (("--extend-test-types", ",".join(TOOLS), "--defer-types", "screw"), None),
        (("--extend-test-types", ",".join(TOOLS), "--defer-types", "pliers"), None),
        (
            ("--defer-types", "pliers,adjustable_wrench"),
            "new object type without decision: allen_key",
        ),
    ],
    ids=["unknown-value", "unknown-member", "listed-not-new", "in-both-lists", "partial-decision"],
)
def test_extra_invalid_type_decisions_exit_2(
    v1_with_tools: SimpleNamespace, tmp_path: Path, extra: tuple[str, ...], needle: str | None
) -> None:
    splits = Path(shutil.copytree(v1_with_tools.splits, tmp_path / "splits"))
    before = snapshot(splits)
    proc = split_cli(v1_with_tools.tools, splits, *extra)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert snapshot(splits) == before
    if needle is not None:
        assert needle in proc.stderr.splitlines()
    assert "Traceback" not in proc.stderr


def test_extra_split_v1_ignores_the_lists(t_tools1: Path, tmp_path: Path) -> None:
    ds = copy_dataset(t_tools1, tmp_path / "ds")
    splits = tmp_path / "splits"
    proc = split_cli(ds, splits, "--defer-types", "pliers")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    v1 = read_split(splits / "split_v1.csv")
    assert any(type_of(p) == "pliers" for p in v1)
    meta = split_json(splits / "split_v1.csv")
    assert meta["deferred_types"] == [] and meta["test_extended_types"] == []


def test_extra_readers_ignore_a_deferred_type(
    ca15: SimpleNamespace, caplog: pytest.LogCaptureFixture
) -> None:
    """Section 4.7: ``rows_for`` ignores the images of a type without lines, with a warning."""
    df = load_manifest(ca15.tools, external_sources=ca15.tools / "external_sources.csv")
    split_df = load_split(ca15.splits / "split_v2.csv")
    with caplog.at_level("WARNING"):
        rows = {w: rows_for(df, split_df, w) for w in SPLITS}
    for w in SPLITS:
        assert not rows[w]["item_id"].astype(str).str.startswith("T-").any(), w
    n_pliers = int((df["object_type"] == "pliers").sum())
    assert f"deferred type images: pliers: {n_pliers}" in caplog.text
    assert sum(len(r) for r in rows.values()) == int((~df["object_type"].isin(TOOLS)).sum())


def test_extra_extension_keeps_one_split_per_item(ca15: SimpleNamespace) -> None:
    v3 = read_split(ca15.splits / "split_v3.csv")
    seen: dict[str, str] = {}
    for path, which in v3.items():
        item = item_of(path)
        assert seen.setdefault(item, which) == which, item  # R-11: one split per item


def test_extra_data_report_lists_tool_coverage_for_mvp_dataset(t_default: Path) -> None:
    df = load_manifest(t_default, external_sources=t_default / "external_sources.csv")
    cov = build_data_report(df)["tool_grade_coverage"]
    assert set(cov) == set(TOOLS)
    for tool in TOOLS:
        assert cov[tool]["graded"] is False
        assert all(c == {"n_images": 0, "n_items": 0} for c in cov[tool]["by_grade"].values())


def test_extra_t_prefix_rules_in_the_manifest(t_tools1: Path, tmp_path: Path) -> None:
    """``S-`` with a tool, ``T-`` with ``other`` and ``XT-`` with ``nut`` are prefix mismatches."""
    for item_id, object_type, grade in (
        ("S-001", "pliers", "good"),
        ("T-001", "other", ""),
        ("T-001", "nut", "good"),
    ):
        root = copy_dataset(t_tools1, tmp_path / f"ds-{item_id}-{object_type}")
        rows = manifest_rows(root)
        idx = next(i for i, r in enumerate(rows) if r["item_id"] == item_id)
        rows[idx]["object_type"] = object_type
        rows[idx]["grade"] = grade
        write_csv_rows(root / "manifest.csv", MANIFEST_HEADER, rows)
        with pytest.raises(ManifestError) as info:
            load_manifest(root, external_sources=root / "external_sources.csv")
        assert "item_prefix_mismatch" in _problem_codes(info), (item_id, object_type)
    assert data_mod.TOOL_GRADE_MIN_IMAGES == 60


def test_extra_thresholds_with_only_tool_images_in_val() -> None:
    """No screw/nut/other image in val: the thresholds stay on the grid, no crash."""
    labels = ModelLabels(
        object_types=("screw", "nut", "other", "pliers"),
        grades=GRADES,
        ungraded_object_types=("pliers",),
    )
    rows = [("pliers", [0.01, 0.01, 0.01, 0.97], [0.2] * 5, -1) for _ in range(6)]
    types = list(labels.object_types)
    preds = Predictions(
        split="val",
        image_paths=tuple(f"raw/pliers/{i}.jpg" for i in range(6)),
        type_probs=np.asarray([r[1] for r in rows]),
        grade_probs=np.asarray([r[2] for r in rows]),
        true_type_idx=np.asarray([types.index(r[0]) for r in rows]),
        true_grade_idx=np.asarray([r[3] for r in rows]),
    )
    result = choose_thresholds(preds, labels)
    assert result.decision.type_threshold == pytest.approx(0.85)
    assert 0.30 <= result.decision.grade_review_threshold <= 0.95
    assert 0.05 <= result.decision.unusable_threshold <= 0.95


def test_extra_ml_decision_matches_the_edge_with_ungraded_types() -> None:
    """The vectorized decision of qc_ml gives the same result as the edge (ADR-021)."""
    from qc_edge.decision import ModelLabels as EdgeLabels
    from qc_edge.decision import Thresholds as EdgeThresholds
    from qc_edge.decision import decide
    from qc_ml.decision import Thresholds as MlThresholds
    from qc_ml.decision import apply_decision

    types = ("screw", "nut", "other", *TOOLS)
    ml_labels = ModelLabels(object_types=types, grades=GRADES, ungraded_object_types=("allen_key",))
    edge_labels = EdgeLabels(
        object_types=types, grades=GRADES, ungraded_object_types=("allen_key",)
    )
    rng = np.random.default_rng(1601)
    type_probs = rng.dirichlet(np.full(len(types), 0.4), size=400)
    grade_probs = rng.dirichlet(np.full(5, 0.6), size=400)
    t = (0.55, 0.45, 0.6)
    out = apply_decision(type_probs, grade_probs, ml_labels, MlThresholds(*t))
    for i in range(400):
        e = decide(type_probs[i], grade_probs[i], edge_labels, EdgeThresholds(*t))
        assert bool(out.needs_review[i]) is e.needs_review, i
        assert out.object_types[i] == e.object_type.value, i
        assert out.grades[i] == (None if e.grade is None else e.grade.value), i
        if e.grade is None:
            assert e.object_type.value in ("unknown", "allen_key"), i
